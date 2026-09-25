"""Practice mode: play a teacher phrase, record my attempt, keep everything aligned.

Two modes:

* ``after`` (call and response): the phrase plays, then the mic records for the
  same length plus a margin while the chart cursor runs over the teacher curve
  again.
* ``along``: the phrase plays and the mic records at the same time.

Both use one full duplex sound card stream (input and output in the same
callback), so the recorded samples are sample-aligned with the playback position.
The callback only moves audio and counts samples; all decisions happen in the UI
thread.

Slowing down without changing pitch uses a phase vocoder (``librosa.effects.
time_stretch``): the sound is cut into overlapping frames and the frames are
re-spaced in time while their spectral content is kept.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from .cents import OCTAVE, hz_to_cents, octave_shift  # noqa: F401 (re-export)
from .config import data_dir
from .live import BlockQueue, PitchStream
from .pitch_offline import PitchCurve, load_curve, curve_path_for, save_curve

IDLE, PLAY, WAIT, RESPOND, DONE = "idle", "play", "wait", "respond", "done"
SPEEDS = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]


@dataclass
class Phrase:
    audio_path: Path
    y: np.ndarray            # samples at the engine sample rate
    sample_rate: int
    curve: PitchCurve | None

    @property
    def name(self) -> str:
        return self.audio_path.stem

    @property
    def duration(self) -> float:
        return self.y.size / self.sample_rate


def load_phrase(path: str | Path, sample_rate: int) -> Phrase:
    """Load a phrase WAV (or its .pitch.json) plus the curve next to it."""
    from .audio_io import load_audio
    path = Path(path)
    if path.name.endswith(".pitch.json"):
        path = path.with_name(path.name[: -len(".pitch.json")] + ".wav")
    y, sr = load_audio(path, sr=sample_rate)
    curve_path = curve_path_for(path)
    curve = load_curve(curve_path) if curve_path.exists() else None
    return Phrase(path, y, sr, curve)


def sibling_phrases(path: Path) -> list[Path]:
    """All phrase WAVs in the same folder, sorted, excluding generated tracks."""
    files = sorted(p for p in path.parent.glob("*.wav")
                   if not p.name.startswith("call_response") and not p.name.endswith(".vocals.wav"))
    return files or [path]


def time_stretch(y: np.ndarray, sr: int, speed: float) -> np.ndarray:
    """Return ``y`` slowed to ``speed`` (0.5 = half speed) without changing pitch."""
    if abs(speed - 1.0) < 1e-6:
        return y
    import librosa
    return librosa.effects.time_stretch(y.astype(np.float32), rate=float(speed)).astype(np.float32)


@dataclass
class Session:
    """Pure state machine for one phrase. Counts samples, never touches audio.

    ``play_len`` is the (possibly stretched) phrase length in samples,
    ``respond_len`` the length of the response window. ``advance`` is called with
    the number of samples the sound card just processed and returns the phase
    that was active during those samples.

    With ``wait_len`` above 0 (mode "after" only) the session pauses in WAIT after
    the phrase until :meth:`trigger` is called, which happens when the singer's
    voice is detected. If nothing happens for ``wait_len`` samples it times out.
    """
    play_len: int
    respond_len: int
    mode: str = "after"
    wait_len: int = 0
    phase: str = IDLE
    pos: int = 0
    attempts: int = 0
    timed_out: bool = False

    def start(self) -> None:
        self.phase, self.pos, self.timed_out = PLAY, 0, False

    def advance(self, frames: int) -> str:
        active = self.phase
        if active in (IDLE, DONE):
            return active
        self.pos += frames
        if active == PLAY and self.pos >= self.play_len:
            if self.mode != "after":
                self.phase = DONE
            elif self.wait_len > 0:
                self.phase, self.pos = WAIT, 0
            else:
                self.phase, self.pos = RESPOND, 0
        elif active == WAIT and self.pos >= self.wait_len:
            self.phase, self.timed_out = DONE, True
        elif active == RESPOND and self.pos >= self.respond_len:
            self.phase = DONE
        return active

    def trigger(self, preroll: int = 0) -> bool:
        """Voice detected while waiting: start the response, ``preroll`` samples in."""
        if self.phase != WAIT:
            return False
        self.phase, self.pos = RESPOND, int(preroll)
        return True

    @property
    def recording_phase(self) -> str:
        return RESPOND if self.mode == "after" else PLAY

    def finish(self) -> None:
        self.phase, self.pos = IDLE, 0
        self.attempts += 1

    def stop(self) -> None:
        self.phase, self.pos = IDLE, 0


class PracticeEngine:
    """Full duplex stream: plays ``play_buffer`` during PLAY, records mic during PLAY/RESPOND."""

    def __init__(self, sample_rate: int, block_size: int, input_device=None, output_device=None,
                 monitor_gain: float = 1.0):
        import sounddevice as sd
        self.sample_rate = int(sample_rate)
        self.block_size = int(block_size)
        self.captured = BlockQueue()
        self.session = Session(0, 0)
        self.play_buffer = np.zeros(0, dtype=np.float32)
        self.gain = float(monitor_gain)
        self._lock = threading.Lock()
        self._stream = sd.Stream(samplerate=self.sample_rate, blocksize=self.block_size,
                                 channels=(1, 1), dtype="float32",
                                 device=(input_device, output_device), latency="low",
                                 callback=self._callback)
        self.input_name = sd.query_devices(self._stream.device[0], "input")["name"]
        self.output_name = sd.query_devices(self._stream.device[1], "output")["name"]
        self.latency = self._stream.latency

    def _callback(self, indata, outdata, frames, time_info, status):
        with self._lock:
            s = self.session
            phase, pos = s.phase, s.pos
            if phase == PLAY:
                chunk = self.play_buffer[pos:pos + frames]
                if chunk.size < frames:
                    chunk = np.concatenate([chunk, np.zeros(frames - chunk.size, dtype=np.float32)])
                outdata[:, 0] = chunk * self.gain
            else:
                outdata.fill(0)
            if phase in (PLAY, WAIT, RESPOND):
                self.captured.put_tagged(phase, pos, indata[:, 0])
            s.advance(frames)

    def begin(self, session: Session, play_buffer: np.ndarray) -> None:
        with self._lock:
            self.session = session
            self.play_buffer = np.ascontiguousarray(play_buffer, dtype=np.float32)
            self.captured.drain()
            session.start()

    def stop_session(self) -> None:
        with self._lock:
            self.session.stop()

    def trigger_respond(self, preroll: int) -> bool:
        with self._lock:
            return self.session.trigger(preroll)

    def start(self) -> None:
        self._stream.start()

    def close(self) -> None:
        self._stream.stop()
        self._stream.close()


class OnsetDetector:
    """Decides when the singer has started: loud enough and pitched for a few frames.

    Feed mic blocks with :meth:`feed`; it returns True once. The last
    ``preroll_seconds`` of audio before that moment are kept in :attr:`preroll`
    so the beginning of the first note is not cut off.
    """

    def __init__(self, detector, hop_length: int, rms_db: float = -40.0,
                 voiced_frames: int = 6, preroll_seconds: float = 0.15):
        from .live import RingBuffer
        self.detector = detector
        self.hop = int(hop_length)
        self.sample_rate = detector.sample_rate
        self.rms_threshold = 10 ** (rms_db / 20)
        self.voiced_frames = int(voiced_frames)
        self._ring = RingBuffer(detector.frame_length)
        self._pending = np.zeros(0, dtype=np.float32)
        self._run = 0
        self._preroll_blocks: list[np.ndarray] = []
        self._preroll_max = int(preroll_seconds * self.sample_rate)
        self.triggered = False

    @property
    def preroll(self) -> np.ndarray:
        if not self._preroll_blocks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self._preroll_blocks)[-self._preroll_max:]

    def feed(self, block: np.ndarray) -> bool:
        if self.triggered:
            return False
        block = np.asarray(block, dtype=np.float32).ravel()
        self._preroll_blocks.append(block)
        while sum(b.size for b in self._preroll_blocks) - self._preroll_blocks[0].size >= self._preroll_max:
            self._preroll_blocks.pop(0)
        self._pending = np.concatenate([self._pending, block])
        while self._pending.size >= self.hop:
            hop, self._pending = self._pending[:self.hop], self._pending[self.hop:]
            self._ring.push(hop)
            if not self._ring.full:
                continue
            frame = self._ring.latest()
            loud = float(np.sqrt(np.mean(frame[-self.hop * 4:] ** 2))) > self.rms_threshold
            voiced = loud and np.isfinite(self.detector.detect(frame))
            self._run = self._run + 1 if voiced else 0
            if self._run >= self.voiced_frames:
                self.triggered = True
                return True
        return False


class Attempt:
    """Collects mic samples and live pitch points for one repetition."""

    def __init__(self, stream: PitchStream, time_offset: float = 0.0):
        """``time_offset`` (seconds) is subtracted from every time stamp. It holds the
        sound card round trip (output plus input latency), so what I sing in reply
        to second 3 of the phrase is drawn at second 3 and not at 3.1."""
        self.stream = stream
        self.time_offset = float(time_offset)
        self.blocks: list[np.ndarray] = []
        self.points: list[tuple[float, float, float]] = []

    def add(self, block: np.ndarray) -> list[tuple[float, float, float]]:
        self.blocks.append(np.asarray(block, dtype=np.float32))
        new = [(t - self.time_offset, f0, c) for t, f0, c in self.stream.process(block)]
        self.points.extend(new)
        return new

    @property
    def audio(self) -> np.ndarray:
        return np.concatenate(self.blocks) if self.blocks else np.zeros(0, dtype=np.float32)

    def curve(self, source: str = "") -> PitchCurve:
        t = np.array([p[0] for p in self.points], dtype=float)
        f0 = np.array([p[1] for p in self.points], dtype=float)
        c = np.array([p[2] for p in self.points], dtype=float)
        return PitchCurve(source=source, sample_rate=self.stream.sample_rate,
                          hop_seconds=self.stream.hop_length / self.stream.sample_rate,
                          tonic_hz=self.stream.tonic_hz, times=t, f0_hz=f0, cents=c,
                          voiced=np.isfinite(f0))


def attempts_dir(phrase: Phrase) -> Path:
    return data_dir() / "attempts" / phrase.audio_path.parent.name / phrase.name


def save_attempt(attempt: Attempt, phrase: Phrase, mode: str, speed: float,
                 teacher_tonic: float, shift: float, out_dir: Path | None = None) -> Path:
    """Write ``<stamp>.wav``, ``<stamp>.pitch.json`` and ``<stamp>.meta.json``."""
    from .audio_io import save_wav
    out_dir = out_dir or attempts_dir(phrase)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    wav = out_dir / f"{stamp}.wav"
    save_wav(wav, attempt.audio, attempt.stream.sample_rate)
    save_curve(attempt.curve(source=wav.name), wav.with_suffix(".pitch.json"))
    meta = {
        "phrase_audio": str(phrase.audio_path),
        "phrase_curve": str(curve_path_for(phrase.audio_path)),
        "mode": mode, "speed": speed,
        "tonic_mine_hz": attempt.stream.tonic_hz, "tonic_teacher_hz": teacher_tonic,
        "octave_shift_cents": shift,
        "latency_offset_seconds": attempt.time_offset,
        "recorded_at": stamp,
    }
    with open(wav.with_suffix(".meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1)
    return wav
