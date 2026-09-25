"""Silence based phrase detection, phrase export, Audacity labels, call-and-response tracks.

The loudness envelope is measured as RMS per frame in dBFS (decibels relative to
full scale, where 0 dB is the loudest possible sample and quiet room noise sits
around -50 dB). A phrase is a stretch of audio between pauses, where a pause is a
run of frames below ``silence_db`` lasting at least ``min_pause_seconds``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .pitch_offline import PitchCurve


@dataclass
class Phrase:
    start: float          # seconds
    end: float            # seconds
    label: str = ""

    @property
    def duration(self) -> float:
        return self.end - self.start


def rms_db(y: np.ndarray, sr: int, frame_length: int = 2048, hop_length: int = 512):
    """Loudness envelope. Returns ``(times, db)`` with one value per hop."""
    import librosa
    rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
    db = 20.0 * np.log10(np.maximum(rms, 1e-9))
    times = librosa.frames_to_time(np.arange(db.size), sr=sr, hop_length=hop_length)
    return times, db


def _runs(mask: np.ndarray):
    """Start and end indices (end exclusive) of runs of True in a boolean array."""
    if mask.size == 0:
        return []
    edges = np.diff(np.concatenate([[0], mask.astype(int), [0]]))
    starts = np.nonzero(edges == 1)[0]
    ends = np.nonzero(edges == -1)[0]
    return list(zip(starts, ends))


def detect_phrases(y: np.ndarray, sr: int, silence_db: float = -40.0,
                   min_pause_seconds: float = 0.6, min_phrase_seconds: float = 0.8,
                   pad_seconds: float = 0.1, frame_length: int = 2048,
                   hop_length: int = 512) -> list[Phrase]:
    """Split a recording into phrases at pauses.

    Frames quieter than ``silence_db`` are silent. A pause must last at least
    ``min_pause_seconds`` to count. Phrases shorter than ``min_phrase_seconds``
    are dropped. Each phrase is extended by ``pad_seconds`` on both sides without
    overlapping its neighbours.
    """
    times, db = rms_db(y, sr, frame_length, hop_length)
    hop_s = hop_length / sr
    total = y.size / sr
    silent = db < silence_db
    min_pause_frames = max(1, int(round(min_pause_seconds / hop_s)))

    # Only long enough silent runs count as pauses; short dips stay inside the phrase.
    pause_mask = np.zeros_like(silent)
    for s, e in _runs(silent):
        if e - s >= min_pause_frames:
            pause_mask[s:e] = True

    phrases = []
    for s, e in _runs(~pause_mask):
        # Trim silent frames at both ends (short dips inside the phrase are kept).
        active = np.nonzero(~silent[s:e])[0]
        if active.size == 0:
            continue
        s2, e2 = s + int(active[0]), s + int(active[-1]) + 1
        start = float(times[s2])
        end = total if e2 >= times.size else float(times[e2])
        if end - start >= min_phrase_seconds:
            phrases.append(Phrase(start, end))

    # Pad, but never past the neighbouring phrase or the file edges.
    for i, ph in enumerate(phrases):
        lo = phrases[i - 1].end if i > 0 else 0.0
        hi = phrases[i + 1].start if i + 1 < len(phrases) else total
        ph.start = max(lo, ph.start - pad_seconds, 0.0)
        ph.end = min(hi, ph.end + pad_seconds, total)
    for i, ph in enumerate(phrases):
        ph.label = ph.label or f"phrase_{i + 1:02d}"
    return phrases


def write_labels(phrases: list[Phrase], path: str | Path) -> Path:
    """Write an Audacity label track (tab separated: start, end, label)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for ph in phrases:
            fh.write(f"{ph.start:.6f}\t{ph.end:.6f}\t{ph.label}\n")
    return path


def read_labels(path: str | Path) -> list[Phrase]:
    """Read an Audacity label track. Point labels (start == end) are ignored."""
    phrases = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("\\"):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            start, end = float(parts[0]), float(parts[1])
            if end <= start:
                continue
            label = parts[2].strip() if len(parts) > 2 else ""
            phrases.append(Phrase(start, end, label))
    phrases.sort(key=lambda p: p.start)
    for i, ph in enumerate(phrases):
        ph.label = ph.label or f"phrase_{i + 1:02d}"
    return phrases


_BAD_FILENAME_CHARS = '<>:"/\|?*'


def safe_filename(label: str) -> str:
    """Make a label usable as a file name on Windows and Linux."""
    out = "".join("_" if ch in _BAD_FILENAME_CHARS or ord(ch) < 32 else ch for ch in label)
    out = out.strip(" .")
    return out or "phrase"


def slice_curve(curve: PitchCurve, start: float, end: float, source: str = "") -> PitchCurve:
    """Cut a time range out of a pitch curve, with times re-based to start at 0."""
    mask = (curve.times >= start) & (curve.times < end)
    return PitchCurve(source=source or curve.source, sample_rate=curve.sample_rate,
                      hop_seconds=curve.hop_seconds, tonic_hz=curve.tonic_hz,
                      times=curve.times[mask] - start, f0_hz=curve.f0_hz[mask],
                      cents=curve.cents[mask], voiced=curve.voiced[mask])


def export_phrases(y: np.ndarray, sr: int, phrases: list[Phrase], out_dir: str | Path,
                   curve: PitchCurve | None = None) -> list[Path]:
    """Write ``<label>.wav`` (and ``<label>.pitch.json`` if a curve is given) per phrase."""
    from .audio_io import save_wav
    from .pitch_offline import save_curve

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for ph in phrases:
        a, b = int(round(ph.start * sr)), int(round(ph.end * sr))
        wav = out_dir / f"{safe_filename(ph.label)}.wav"
        save_wav(wav, y[a:b], sr)
        written.append(wav)
        if curve is not None:
            save_curve(slice_curve(curve, ph.start, ph.end, source=wav.name),
                       wav.with_suffix(".pitch.json"))
    return written


def build_call_response(y: np.ndarray, sr: int, phrases: list[Phrase],
                        margin_seconds: float = 0.5, lead_in_seconds: float = 0.0):
    """One track: each phrase followed by silence of the same length plus a margin.

    Returns ``(track, labels)`` where ``labels`` marks every call and response
    region so the track can be opened in Audacity with the label file next to it.
    """
    pieces = []
    labels = []
    t = 0.0
    if lead_in_seconds > 0:
        pieces.append(np.zeros(int(round(lead_in_seconds * sr)), dtype=np.float32))
        t += lead_in_seconds
    for ph in phrases:
        a, b = int(round(ph.start * sr)), int(round(ph.end * sr))
        call = np.asarray(y[a:b], dtype=np.float32)
        gap = np.zeros(call.size + int(round(margin_seconds * sr)), dtype=np.float32)
        call_len = call.size / sr
        gap_len = gap.size / sr
        labels.append(Phrase(t, t + call_len, ph.label))
        labels.append(Phrase(t + call_len, t + call_len + gap_len, f"{ph.label}_you"))
        pieces.extend([call, gap])
        t += call_len + gap_len
    if not pieces:
        return np.zeros(0, dtype=np.float32), []
    return np.concatenate(pieces), labels
