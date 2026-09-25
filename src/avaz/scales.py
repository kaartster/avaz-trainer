"""Scale definitions in cents, nearest-note lookup, and calibration from histograms."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

from .cents import OCTAVE
from .config import config_dir


@dataclass
class Scale:
    name: str
    positions: list[float]
    labels: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.positions = [float(p) for p in self.positions]
        if not self.labels:
            self.labels = [f"{p:.0f}" for p in self.positions]
        if len(self.labels) != len(self.positions):
            raise ValueError(f"scale {self.name}: {len(self.labels)} labels for "
                             f"{len(self.positions)} positions")

    def _base(self):
        pairs = [(p, l) for p, l in zip(self.positions, self.labels) if 0 <= p < OCTAVE]
        return [p for p, _ in pairs], [l for _, l in pairs]

    def positions_in_range(self, lo_cents: float, hi_cents: float):
        """All (cents, label) pairs of this scale, repeated over octaves, inside [lo, hi]."""
        base, base_labels = self._base()
        out = []
        k_lo = int(np.floor(lo_cents / OCTAVE)) - 1
        k_hi = int(np.ceil(hi_cents / OCTAVE)) + 1
        for k in range(k_lo, k_hi + 1):
            for p, l in zip(base, base_labels):
                c = p + k * OCTAVE
                if lo_cents <= c <= hi_cents:
                    out.append((c, l))
        return out


def load_scales(path: Path | None = None) -> dict[str, Scale]:
    path = path or (config_dir() / "scales.yaml")
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    scales = {}
    for name, entry in raw.items():
        if isinstance(entry, dict):
            scales[name] = Scale(name, entry["positions"], entry.get("labels") or [])
        else:
            scales[name] = Scale(name, list(entry))
    return scales


def nearest_note(cents: float, scale: Scale):
    """Return ``(position_cents, label, deviation_cents)`` of the scale note closest to ``cents``.

    The scale is treated as repeating every octave, so 1350 cents on a scale with a
    note at 150 gives position 1350, deviation 0. NaN input gives ``(nan, "", nan)``.
    """
    if not np.isfinite(cents):
        return float("nan"), "", float("nan")
    base, labels = scale._base()
    base = np.array(base)
    octave = np.floor(cents / OCTAVE) * OCTAVE
    candidates = np.concatenate([base + octave - OCTAVE, base + octave, base + octave + OCTAVE])
    cand_labels = labels * 3
    i = int(np.argmin(np.abs(candidates - cents)))
    return float(candidates[i]), cand_labels[i], float(cents - candidates[i])


def find_histogram_peaks(centers, counts, min_separation_cents: float = 60.0,
                         min_height_fraction: float = 0.08, max_peaks: int = 12):
    """Find prominent peaks in a folded pitch histogram.

    A bin is a peak if it is the highest within ``min_separation_cents`` on both sides
    (circularly) and at least ``min_height_fraction`` of the tallest bin. Returns a
    list of ``(cents, height)`` sorted by cents.
    """
    centers = np.asarray(centers, dtype=float)
    counts = np.asarray(counts, dtype=float)
    if counts.size == 0 or counts.max() <= 0:
        return []
    bin_w = float(centers[1] - centers[0]) if centers.size > 1 else 10.0
    half = max(1, int(round(min_separation_cents / bin_w)))
    n = counts.size
    peaks = []
    for i in range(n):
        idx = [(i + d) % n for d in range(-half, half + 1) if d != 0]
        if counts[i] >= counts[idx].max() and counts[i] >= min_height_fraction * counts.max():
            if counts[i] > counts[(i - 1) % n] or counts[i] > counts[(i + 1) % n]:
                peaks.append((float(centers[i]), float(counts[i])))
    peaks.sort(key=lambda p: p[1], reverse=True)
    peaks = peaks[:max_peaks]
    peaks.sort(key=lambda p: p[0])
    return peaks


def suggest_scale_positions(centers, counts, **kwargs) -> list[float]:
    """Suggest scale positions (cents above tonic, tonic = 0) from a folded histogram.

    The histogram must already be relative to the tonic. A peak within 50 cents of 0
    (or 1200) is snapped to 0. Returns positions in [0, 1200) plus 1200.
    """
    peaks = find_histogram_peaks(centers, counts, **kwargs)
    positions = []
    for c, _h in peaks:
        c = c % OCTAVE
        if c > OCTAVE - 50:
            c -= OCTAVE
        positions.append(0.0 if abs(c) <= 50 else round(c, 1))
    positions = sorted(set(positions))
    if 0.0 not in positions:
        positions.insert(0, 0.0)
    return [p for p in positions if 0 <= p < OCTAVE] + [OCTAVE]
