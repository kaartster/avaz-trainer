"""Compare an attempt with a reference curve: DTW alignment, scores, worst sections, history.

DTW (dynamic time warping) finds the cheapest way to pair up two sequences when
one is faster or slower than the other in places. Each pair costs the absolute
difference in cents; the path may repeat a frame of either sequence to stretch
it. That makes the score tolerant of small timing differences while still
punishing wrong pitches.

Steps:

1. Resample both curves to fixed bins (default 20 ms, median of the frames in
   each bin) so the alignment is cheap and both sides use the same time grid.
2. Keep only voiced bins. Pauses are not scored.
3. Shift the attempt by whole octaves so its median lands on the reference's.
4. Align with DTW inside a band around the diagonal.
5. Per aligned pair: deviation = attempt minus reference (positive = sharp).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

import numpy as np

from .cents import OCTAVE, octave_shift
from .pitch_offline import PitchCurve


@dataclass
class Section:
    start: float          # seconds in the reference timeline
    end: float
    mean_dev: float       # signed, cents (positive = sharp)
    max_abs_dev: float
    mean_abs_dev: float = 0.0

    @property
    def duration(self) -> float:
        return self.end - self.start

    def describe(self) -> str:
        if abs(self.mean_dev) >= 0.6 * self.mean_abs_dev:
            direction = "sharp" if self.mean_dev > 0 else "flat"
            what = f"{direction} by {abs(self.mean_dev):3.0f} cents"
        else:
            what = f"unsteady, off by {self.mean_abs_dev:3.0f} cents on average"
        return f"{self.start:5.2f} - {self.end:5.2f} s  {what} (worst {self.max_abs_dev:.0f})"


@dataclass
class ScoreResult:
    mad: float                    # mean absolute deviation, cents
    median_abs: float
    pct_within: float             # percentage of aligned pairs within tolerance
    tolerance: float
    octave_shift: float
    timing_ratio: float           # attempt voiced length / reference voiced length
    n_pairs: int
    worst: list[Section]
    median_offset: float = 0.0    # attempt median minus reference median, cents (+ = sharp)
    # for plots: reference timeline with the attempt warped onto it
    ref_times: np.ndarray = field(repr=False, default=None)
    ref_cents: np.ndarray = field(repr=False, default=None)
    att_on_ref: np.ndarray = field(repr=False, default=None)
    dev_on_ref: np.ndarray = field(repr=False, default=None)
    att_times: np.ndarray = field(repr=False, default=None)
    att_cents: np.ndarray = field(repr=False, default=None)

    def summary(self) -> str:
        lines = [f"within {self.tolerance:.0f} cents: {self.pct_within:.0f}%   "
                 f"mean deviation: {self.mad:.0f} cents   median: {self.median_abs:.0f} cents   "
                 f"timing: {100 * self.timing_ratio:.0f}% of the teacher's length"]
        if abs(self.median_offset) >= 10:
            direction = "sharp" if self.median_offset > 0 else "flat"
            lines.append(f"overall {direction} by {abs(self.median_offset):.0f} cents "
                         f"(median of the whole attempt against the teacher)")
        if self.octave_shift:
            lines.append(f"(attempt shifted by {self.octave_shift:+.0f} cents to match the octave)")
        if self.worst:
            lines.append("worst sections (reference time):")
            lines += ["  " + s.describe() for s in self.worst]
        return "\n".join(lines)

    def to_record(self) -> dict:
        return {"mad": round(self.mad, 1), "median_abs": round(self.median_abs, 1),
                "pct_within": round(self.pct_within, 1), "tolerance": self.tolerance,
                "octave_shift": self.octave_shift, "timing_ratio": round(self.timing_ratio, 3),
                "median_offset": round(self.median_offset, 1),
                "n_pairs": self.n_pairs,
                "worst": [[round(s.start, 2), round(s.end, 2), round(s.mean_dev, 1)] for s in self.worst]}


def resample_to_bins(times, cents, bin_seconds: float = 0.02, t_end: float | None = None):
    """Median of the voiced values in each ``bin_seconds`` bin. Empty bins are NaN."""
    times = np.asarray(times, dtype=float)
    cents = np.asarray(cents, dtype=float)
    if times.size == 0:
        return np.zeros(0), np.zeros(0)
    t_end = t_end if t_end is not None else float(times.max()) + 1e-9
    n = max(1, int(np.ceil(t_end / bin_seconds)))
    idx = np.clip((times / bin_seconds).astype(int), 0, n - 1)
    out = np.full(n, np.nan)
    finite = np.isfinite(cents)
    for b in np.unique(idx[finite]):
        out[b] = np.median(cents[finite & (idx == b)])
    centers = (np.arange(n) + 0.5) * bin_seconds
    return centers, out


def dtw_align(a: np.ndarray, b: np.ndarray, band: float = 0.2) -> np.ndarray:
    """Alignment path between two 1-D sequences. Returns ``(k, 2)`` index pairs, in order.

    ``band`` limits how far from the diagonal the path may wander, as a fraction
    of the longer sequence, so a phrase cannot be matched to a totally different
    part of the reference.
    """
    from librosa.sequence import dtw
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.size == 0 or b.size == 0:
        return np.zeros((0, 2), dtype=int)
    cost = np.abs(a[:, None] - b[None, :])
    n, m = cost.shape
    if n == 1 or m == 1:
        return np.array([(i, j) for i in range(n) for j in range(m)], dtype=int)
    rad = max(band, abs(n - m) / max(n, m) + 1.0 / max(n, m))
    # Plain steps with equal weights. Slope limits and pre-smoothing were tried on
    # real attempts and both aligned worse, because an attempt often misses whole
    # bits of the reference and the path must be free to park there.
    try:
        _, wp = dtw(C=cost, global_constraints=True, band_rad=float(rad), backtrack=True)
    except Exception:
        _, wp = dtw(C=cost, backtrack=True)
    return np.asarray(wp[::-1], dtype=int)


def worst_sections(times, dev, tolerance: float, min_seconds: float = 0.2,
                   merge_gap: float = 0.15, max_sections: int = 5) -> list[Section]:
    """Stretches of the reference timeline where |deviation| exceeds the tolerance."""
    times = np.asarray(times, dtype=float)
    dev = np.asarray(dev, dtype=float)
    bad = np.isfinite(dev) & (np.abs(dev) > tolerance)
    if not bad.any():
        return []
    edges = np.diff(np.concatenate([[0], bad.astype(int), [0]]))
    runs = list(zip(np.nonzero(edges == 1)[0], np.nonzero(edges == -1)[0]))
    step = float(times[1] - times[0]) if times.size > 1 else 0.02
    merged = []
    for s, e in runs:
        if merged and (s - merged[-1][1]) * step <= merge_gap:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    sections = []
    for s, e in merged:
        if (e - s) * step < min_seconds:
            continue
        d = dev[s:e]
        d = d[np.isfinite(d)]
        mean_abs = float(np.abs(d).mean())
        if mean_abs <= tolerance:
            continue          # merged run whose bins are mostly fine: not a real problem
        sections.append(Section(float(times[s] - step / 2), float(times[e - 1] + step / 2),
                                float(np.mean(d)), float(np.abs(d).max()), mean_abs))
    sections.sort(key=lambda sec: sec.mean_abs_dev * sec.duration, reverse=True)
    return sections[:max_sections]


def score_curves(reference: PitchCurve, attempt: PitchCurve, tolerance: float = 25.0,
                 bin_seconds: float = 0.02, band: float = 0.2, fold: bool = True) -> ScoreResult:
    """Align ``attempt`` to ``reference`` (both in cents relative to their own tonic)."""
    rt, rc = resample_to_bins(reference.times, reference.cents, bin_seconds)
    at, ac = resample_to_bins(attempt.times, attempt.cents, bin_seconds)
    shift = octave_shift(ac, rc, min_points=5) if fold else 0.0
    ac = ac + shift

    ri = np.nonzero(np.isfinite(rc))[0]
    ai = np.nonzero(np.isfinite(ac))[0]
    if ri.size == 0 or ai.size == 0:
        # Keyword arguments here on purpose: a positional call broke silently the
        # last time a field was added to ScoreResult, shifting every value after it.
        return ScoreResult(mad=float("nan"), median_abs=float("nan"), pct_within=0.0,
                           tolerance=tolerance, octave_shift=shift, timing_ratio=0.0, n_pairs=0,
                           worst=[], median_offset=float("nan"),
                           ref_times=rt, ref_cents=rc, att_on_ref=np.full_like(rc, np.nan),
                           dev_on_ref=np.full_like(rc, np.nan), att_times=at, att_cents=ac)

    path = dtw_align(rc[ri], ac[ai], band=band)
    dev_pairs = ac[ai[path[:, 1]]] - rc[ri[path[:, 0]]]
    abs_dev = np.abs(dev_pairs)

    # Attempt warped onto the reference grid: mean of the matched attempt values per ref bin.
    att_on_ref = np.full_like(rc, np.nan)
    dev_on_ref = np.full_like(rc, np.nan)
    sums = np.zeros_like(rc)
    counts = np.zeros_like(rc)
    np.add.at(sums, ri[path[:, 0]], ac[ai[path[:, 1]]])
    np.add.at(counts, ri[path[:, 0]], 1)
    hit = counts > 0
    att_on_ref[hit] = sums[hit] / counts[hit]
    dev_on_ref[hit] = att_on_ref[hit] - rc[hit]

    return ScoreResult(
        mad=float(abs_dev.mean()), median_abs=float(np.median(abs_dev)),
        pct_within=float(100 * (abs_dev <= tolerance).mean()), tolerance=float(tolerance),
        octave_shift=float(shift), timing_ratio=float(ai.size / ri.size), n_pairs=int(path.shape[0]),
        median_offset=float(np.median(ac[ai]) - np.median(rc[ri])),
        worst=worst_sections(rt, dev_on_ref, tolerance),
        ref_times=rt, ref_cents=rc, att_on_ref=att_on_ref, dev_on_ref=dev_on_ref,
        att_times=at, att_cents=ac)


def score_attempt(reference: PitchCurve, attempt: PitchCurve, tolerance: float = 25.0,
                  same_key: bool = False, **kwargs) -> ScoreResult:
    """:func:`score_curves` with the song's key choice applied.

    In the same key, the teacher sang in my range, so my pitch is compared as it
    is: both curves are measured from the teacher's tonic and nothing is shifted
    by octaves. Otherwise each curve stays relative to its own singer's tonic and
    octave differences are folded away.
    """
    if same_key:
        attempt = attempt.with_tonic(reference.tonic_hz)
    return score_curves(reference, attempt, tolerance=tolerance, fold=not same_key, **kwargs)


# ------------------------------------------------------------------ attempts and history

def read_meta(attempt_wav: Path) -> dict:
    meta_path = Path(attempt_wav).with_suffix(".meta.json")
    if not meta_path.exists():
        return {}
    with open(meta_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def reference_for(attempt_wav: Path) -> Path | None:
    """The reference curve named in the attempt's meta file, if it still exists."""
    meta = read_meta(attempt_wav)
    ref = meta.get("phrase_curve")
    if ref and Path(ref).exists():
        return Path(ref)
    return None


def attempt_curve(attempt_wav: Path, method: str = "offline", settings: dict | None = None,
                  tonic_hz: float | None = None) -> PitchCurve:
    """The attempt's pitch curve: ``live`` reads the saved one, ``offline`` runs pyin."""
    from .pitch_offline import analyze_file, load_curve
    attempt_wav = Path(attempt_wav)
    live_path = attempt_wav.with_suffix(".pitch.json")
    if method == "live":
        curve = load_curve(live_path)
        return curve.with_tonic(tonic_hz) if tonic_hz else curve
    if tonic_hz is None:
        meta = read_meta(attempt_wav)
        tonic_hz = meta.get("tonic_mine_hz")
        if tonic_hz is None and live_path.exists():
            tonic_hz = load_curve(live_path).tonic_hz
    return analyze_file(attempt_wav, tonic_hz=float(tonic_hz), settings=settings or {})


def history_path(attempt_wav: Path) -> Path:
    return Path(attempt_wav).parent / "history.json"


def load_history(path: Path) -> dict:
    if not Path(path).exists():
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def record_score(attempt_wav: Path, result: ScoreResult, method: str) -> Path:
    """Store the score under the attempt's name (one entry per attempt; rescoring replaces)."""
    attempt_wav = Path(attempt_wav)
    path = history_path(attempt_wav)
    hist = load_history(path)
    meta = read_meta(attempt_wav)
    entry = result.to_record()
    entry.update({"method": method, "mode": meta.get("mode"), "speed": meta.get("speed"),
                  "recorded_at": meta.get("recorded_at") or attempt_wav.stem,
                  "scored_at": datetime.now().strftime("%Y%m%d_%H%M%S")})
    hist[attempt_wav.stem] = entry
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(hist, fh, indent=1)
    return path


def history_rows(hist: dict) -> list[dict]:
    rows = [dict(name=k, **v) for k, v in hist.items()]
    rows.sort(key=lambda r: r.get("recorded_at", r["name"]))
    return rows
