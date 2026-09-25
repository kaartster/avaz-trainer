"""Offline pitch analysis of recordings with librosa's pyin, plus curve file I/O.

pyin ("probabilistic YIN") runs YIN on every frame but keeps several candidate
periods with probabilities and then picks the smoothest path through them. It is
slower than plain YIN but much cleaner on real voice recordings, so it is used for
all offline work. Live detection uses the faster plain YIN in ``pitch_live``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np

from .cents import hz_to_cents, estimate_tonic


@dataclass
class PitchCurve:
    source: str
    sample_rate: int
    hop_seconds: float
    tonic_hz: float
    times: np.ndarray
    f0_hz: np.ndarray
    cents: np.ndarray
    voiced: np.ndarray

    @property
    def duration(self) -> float:
        return float(self.times[-1] + self.hop_seconds) if self.times.size else 0.0

    def with_tonic(self, tonic_hz: float) -> "PitchCurve":
        """Same curve, cents recomputed against a different tonic."""
        return PitchCurve(self.source, self.sample_rate, self.hop_seconds, float(tonic_hz),
                          self.times, self.f0_hz, hz_to_cents(self.f0_hz, tonic_hz), self.voiced)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["times"] = [round(float(t), 5) for t in self.times]
        d["f0_hz"] = [None if not np.isfinite(v) else round(float(v), 3) for v in self.f0_hz]
        d["cents"] = [None if not np.isfinite(v) else round(float(v), 1) for v in self.cents]
        d["voiced"] = [bool(v) for v in self.voiced]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "PitchCurve":
        f0 = np.array([np.nan if v is None else v for v in d["f0_hz"]], dtype=float)
        cents = np.array([np.nan if v is None else v for v in d["cents"]], dtype=float)
        return cls(source=d["source"], sample_rate=int(d["sample_rate"]),
                   hop_seconds=float(d["hop_seconds"]), tonic_hz=float(d["tonic_hz"]),
                   times=np.asarray(d["times"], dtype=float), f0_hz=f0, cents=cents,
                   voiced=np.asarray(d["voiced"], dtype=bool))


def save_curve(curve: PitchCurve, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(curve.to_dict(), fh)
    return path


def load_curve(path: str | Path) -> PitchCurve:
    with open(path, "r", encoding="utf-8") as fh:
        return PitchCurve.from_dict(json.load(fh))


def remove_short_islands(f0: np.ndarray, min_frames: int) -> np.ndarray:
    """Set voiced runs shorter than ``min_frames`` to NaN. They are mostly clicks."""
    f0 = f0.copy()
    voiced = np.isfinite(f0)
    if not voiced.any() or min_frames <= 1:
        return f0
    edges = np.diff(np.concatenate([[0], voiced.astype(int), [0]]))
    starts = np.nonzero(edges == 1)[0]
    ends = np.nonzero(edges == -1)[0]
    for s, e in zip(starts, ends):
        if e - s < min_frames:
            f0[s:e] = np.nan
    return f0


def remove_outliers(f0: np.ndarray, max_cents_from_median: float) -> np.ndarray:
    """Blank voiced frames further than ``max_cents_from_median`` from the median pitch.

    One singer rarely spans more than two octaves in one recording, so frames far
    outside that are detector slips (noise after vocal separation, clicks, breath).
    A value of 0 disables the filter.
    """
    if max_cents_from_median <= 0:
        return f0
    f0 = f0.copy()
    voiced = np.isfinite(f0) & (f0 > 0)
    if not voiced.any():
        return f0
    median = float(np.median(f0[voiced]))
    with np.errstate(invalid="ignore", divide="ignore"):
        dist = np.abs(hz_to_cents(f0, median))
    f0[voiced & (dist > max_cents_from_median)] = np.nan
    return f0


def analyze_audio(y: np.ndarray, sr: int, tonic_hz: float | str | None = "auto",
                  frame_length: int = 2048, hop_length: int = 256,
                  fmin: float = 70.0, fmax: float = 1000.0,
                  voiced_prob_threshold: float = 0.0, min_voiced_seconds: float = 0.03,
                  max_cents_from_median: float = 1500.0,
                  source: str = "") -> PitchCurve:
    """Run pyin on a mono signal and return a :class:`PitchCurve`.

    ``tonic_hz`` may be a number, "auto" (histogram peak), "final" (last sustained
    note) or None (same as "auto").
    """
    import librosa

    f0, voiced_flag, voiced_prob = librosa.pyin(
        y.astype(np.float32), fmin=fmin, fmax=fmax, sr=sr,
        frame_length=frame_length, hop_length=hop_length, fill_na=np.nan)
    f0 = np.asarray(f0, dtype=float)
    # pyin's Viterbi path decides voiced/unvoiced (fill_na already blanks unvoiced
    # frames). voiced_prob is a much stricter measure and is only applied when a
    # threshold above 0 is requested.
    f0[~np.asarray(voiced_flag, dtype=bool)] = np.nan
    if voiced_prob_threshold > 0:
        f0[voiced_prob < voiced_prob_threshold] = np.nan
    hop_seconds = hop_length / sr
    f0 = remove_outliers(f0, max_cents_from_median)
    f0 = remove_short_islands(f0, int(round(min_voiced_seconds / hop_seconds)))
    voiced = np.isfinite(f0)
    times = librosa.frames_to_time(np.arange(f0.size), sr=sr, hop_length=hop_length)

    if tonic_hz in (None, "auto", "histogram"):
        tonic = estimate_tonic(f0, method="histogram")
    elif tonic_hz == "final":
        tonic = estimate_tonic(f0, method="final", hop_seconds=hop_seconds)
    else:
        tonic = float(tonic_hz)

    return PitchCurve(source=source, sample_rate=int(sr), hop_seconds=float(hop_seconds),
                      tonic_hz=float(tonic), times=times, f0_hz=f0,
                      cents=hz_to_cents(f0, tonic), voiced=voiced)


def analyze_file(path: str | Path, tonic_hz: float | str | None = "auto",
                 settings: dict | None = None, sr: int | None = None) -> PitchCurve:
    """Load a file and analyze it using the ``audio`` and ``offline`` sections of settings."""
    from .audio_io import load_audio

    settings = settings or {}
    audio = settings.get("audio", {})
    offline = settings.get("offline", {})
    y, sr = load_audio(path, sr=sr)
    return analyze_audio(
        y, sr, tonic_hz=tonic_hz,
        frame_length=int(audio.get("frame_length", 2048)),
        hop_length=int(audio.get("hop_length", 256)),
        fmin=float(audio.get("fmin_hz", 70)), fmax=float(audio.get("fmax_hz", 1000)),
        voiced_prob_threshold=float(offline.get("voiced_prob_threshold", 0.0)),
        min_voiced_seconds=float(offline.get("min_voiced_seconds", 0.03)),
        max_cents_from_median=float(offline.get("max_cents_from_median", 1500)),
        source=Path(path).name)


def curve_path_for(audio_path: str | Path) -> Path:
    """Where the pitch curve JSON of an audio file lives: next to it, same stem."""
    p = Path(audio_path)
    return p.with_suffix(".pitch.json")
