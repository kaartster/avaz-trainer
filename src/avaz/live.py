"""Live pitch pipeline: audio blocks in, (time, cents) points out.

Audio arrives from the sound card in small *blocks* (for example 256 samples,
about 6 ms at 44100 Hz). The pitch detector needs a longer *frame* (2048 samples,
46 ms) to see a few periods of the lowest note, so blocks are appended to a ring
buffer and the detector runs on the most recent frame every time a new block
arrives. The delay from voice to pitch value is therefore about half a frame plus
one block, roughly 30 ms, which is well under the 100 ms target.

Nothing in this module touches the sound card or the screen, so it can be tested
with synthetic blocks.
"""

from __future__ import annotations

import queue
import threading
from collections import deque

import numpy as np

from .cents import hz_to_cents
from .pitch_live import PitchDetector, create_detector


class RingBuffer:
    """Fixed size buffer that always holds the most recent ``size`` samples."""

    def __init__(self, size: int):
        self.size = int(size)
        self._buf = np.zeros(self.size, dtype=np.float32)
        self._filled = 0

    def push(self, block: np.ndarray) -> None:
        block = np.asarray(block, dtype=np.float32).ravel()
        n = block.size
        if n >= self.size:
            self._buf[:] = block[-self.size:]
        else:
            self._buf = np.roll(self._buf, -n)
            self._buf[-n:] = block
        self._filled = min(self.size, self._filled + n)

    @property
    def full(self) -> bool:
        return self._filled >= self.size

    def latest(self) -> np.ndarray:
        return self._buf


class PitchStream:
    """Turns audio blocks into (time, f0, cents) points, with optional median smoothing.

    Call :meth:`process` for each block; it returns the new points. Smoothing uses a
    median over the last ``smoothing_frames`` detections, which kills single-frame
    slips without softening a real tahrir much. NaN (unvoiced) values in the window
    make the output NaN when they are the majority.
    """

    def __init__(self, detector: PitchDetector, tonic_hz: float, hop_length: int,
                 smoothing_frames: int = 1):
        self.detector = detector
        self.tonic_hz = float(tonic_hz)
        self.hop_length = int(hop_length)
        self.sample_rate = detector.sample_rate
        self.smoothing_frames = max(1, int(smoothing_frames))
        self._ring = RingBuffer(detector.frame_length)
        self._pending = np.zeros(0, dtype=np.float32)
        self._samples_seen = 0
        self._recent = deque(maxlen=self.smoothing_frames)

    def _smooth(self, f0: float) -> float:
        self._recent.append(f0)
        if self.smoothing_frames == 1:
            return f0
        vals = np.array(self._recent, dtype=float)
        finite = vals[np.isfinite(vals)]
        if finite.size * 2 <= vals.size:
            return float("nan")
        return float(np.median(finite))

    def process(self, block: np.ndarray) -> list[tuple[float, float, float]]:
        """Feed one block of samples. Returns new ``(time_s, f0_hz, cents)`` points."""
        block = np.asarray(block, dtype=np.float32).ravel()
        self._pending = np.concatenate([self._pending, block])
        out = []
        while self._pending.size >= self.hop_length:
            hop, self._pending = self._pending[:self.hop_length], self._pending[self.hop_length:]
            self._ring.push(hop)
            self._samples_seen += self.hop_length
            if not self._ring.full:
                continue
            f0 = self.detector.detect(self._ring.latest())
            f0 = self._smooth(f0)
            # Time stamp at the centre of the analysis frame
            t = (self._samples_seen - self.detector.frame_length / 2) / self.sample_rate
            out.append((t, f0, hz_to_cents(f0, self.tonic_hz)))
        return out


class LiveTrace:
    """Rolling history of (time, cents) for the scrolling chart."""

    def __init__(self, history_seconds: float, hop_seconds: float):
        self.history_seconds = float(history_seconds)
        n = int(np.ceil(history_seconds / hop_seconds)) + 8
        self.times = np.full(n, np.nan)
        self.cents = np.full(n, np.nan)
        self.f0 = np.full(n, np.nan)
        self._count = 0

    def append(self, points) -> None:
        for t, f0, c in points:
            self.times = np.roll(self.times, -1)
            self.cents = np.roll(self.cents, -1)
            self.f0 = np.roll(self.f0, -1)
            self.times[-1], self.cents[-1], self.f0[-1] = t, c, f0
            self._count += 1

    @property
    def latest_time(self) -> float:
        return float(self.times[-1]) if self._count else 0.0

    @property
    def latest_cents(self) -> float:
        return float(self.cents[-1]) if self._count else float("nan")

    def window(self):
        """(times, cents) inside the last ``history_seconds``, oldest first."""
        if self._count == 0:
            return np.zeros(0), np.zeros(0)
        lo = self.latest_time - self.history_seconds
        mask = np.isfinite(self.times) & (self.times >= lo)
        return self.times[mask], self.cents[mask]

    def stable_cents(self, seconds: float = 0.3) -> float:
        """Median of the recent voiced values, for the numeric readout."""
        if self._count == 0:
            return float("nan")
        lo = self.latest_time - seconds
        mask = np.isfinite(self.times) & (self.times >= lo) & np.isfinite(self.cents)
        if mask.sum() < 3:
            return float("nan")
        return float(np.median(self.cents[mask]))


class BlockQueue:
    """Thread safe hand-off of audio blocks from the sound card callback to the UI."""

    def __init__(self):
        self._q: queue.Queue = queue.Queue()

    def put(self, block: np.ndarray) -> None:
        self._q.put(np.array(block, dtype=np.float32).ravel())

    def put_tagged(self, phase: str, pos: int, block: np.ndarray) -> None:
        """Store a block together with the phase and sample position it was recorded at."""
        self._q.put((phase, int(pos), np.array(block, dtype=np.float32).ravel()))

    def drain(self) -> list:
        out = []
        while True:
            try:
                out.append(self._q.get_nowait())
            except queue.Empty:
                return out


class MicSource:
    """Microphone input via sounddevice. Blocks land in :attr:`blocks`."""

    def __init__(self, sample_rate: int, block_size: int, device=None):
        import sounddevice as sd
        self.blocks = BlockQueue()
        self.sample_rate = int(sample_rate)
        self.block_size = int(block_size)
        self.device = device
        self._stream = sd.InputStream(samplerate=self.sample_rate, blocksize=self.block_size,
                                      channels=1, dtype="float32", device=device,
                                      callback=self._callback)
        info = sd.query_devices(self._stream.device, "input")
        self.name = info["name"]

    def _callback(self, indata, frames, time_info, status):
        self.blocks.put(indata[:, 0])

    def start(self) -> None:
        self._stream.start()

    def stop(self) -> None:
        self._stream.stop()
        self._stream.close()


class FileSource:
    """Plays a file through the speakers and feeds the same samples to the pipeline.

    Used to test the live view without singing: the curve should follow the file.
    """

    def __init__(self, path, sample_rate: int, block_size: int, device=None, loop: bool = True):
        import sounddevice as sd
        from .audio_io import load_audio
        self.blocks = BlockQueue()
        self.sample_rate = int(sample_rate)
        self.block_size = int(block_size)
        self.y, _ = load_audio(path, sr=self.sample_rate)
        self.loop = loop
        self.pos = 0
        self.name = f"file: {path}"
        self._stream = sd.OutputStream(samplerate=self.sample_rate, blocksize=self.block_size,
                                       channels=1, dtype="float32", device=device,
                                       callback=self._callback)

    def _callback(self, outdata, frames, time_info, status):
        chunk = self.y[self.pos:self.pos + frames]
        if chunk.size < frames:
            if self.loop and self.y.size:
                self.pos = 0
                chunk = np.concatenate([chunk, self.y[: frames - chunk.size]])
            else:
                chunk = np.concatenate([chunk, np.zeros(frames - chunk.size, dtype=np.float32)])
        self.pos += frames
        outdata[:, 0] = chunk
        self.blocks.put(chunk)

    def start(self) -> None:
        self._stream.start()

    def stop(self) -> None:
        self._stream.stop()
        self._stream.close()


def build_pitch_stream(settings: dict, tonic_hz: float, backend: str = "auto",
                       sample_rate: int | None = None, hop_length: int | None = None,
                       smoothing_frames: int | None = None) -> PitchStream:
    audio = settings.get("audio", {})
    live = settings.get("live", {})
    sr = int(sample_rate or audio.get("sample_rate", 44100))
    hop = int(hop_length or audio.get("hop_length", 256))
    detector = create_detector(backend, sample_rate=sr,
                               frame_length=int(audio.get("frame_length", 2048)),
                               fmin=float(audio.get("fmin_hz", 70)),
                               fmax=float(audio.get("fmax_hz", 1000)),
                               silence_rms=10 ** (float(audio.get("pitch_silence_db", -46)) / 20))
    smooth = live.get("smoothing_frames", 3) if smoothing_frames is None else smoothing_frames
    return PitchStream(detector, tonic_hz, hop, smoothing_frames=int(smooth))
