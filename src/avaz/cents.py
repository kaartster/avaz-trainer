"""Conversions between Hz and cents, octave folding, tonic estimation, histograms.

Cents are a logarithmic pitch unit: 1200 cents is one octave, 100 cents is one
equal tempered semitone. Everything in this project is displayed and compared in
cents relative to a tonic frequency so that two singers in different keys can be
compared directly.

Unvoiced frames are represented as NaN throughout and propagate through these
functions unchanged.
"""

from __future__ import annotations

import numpy as np

OCTAVE = 1200.0


def hz_to_cents(f0_hz, tonic_hz: float):
    """Convert frequency in Hz to cents relative to ``tonic_hz``.

    Works on scalars and numpy arrays. Non positive or NaN frequencies become NaN.
    """
    f0 = np.asarray(f0_hz, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = OCTAVE * np.log2(f0 / float(tonic_hz))
    out = np.where(f0 > 0, out, np.nan)
    if out.ndim == 0:
        return float(out)
    return out


def cents_to_hz(cents, tonic_hz: float):
    """Inverse of :func:`hz_to_cents`."""
    c = np.asarray(cents, dtype=float)
    out = float(tonic_hz) * np.power(2.0, c / OCTAVE)
    if out.ndim == 0:
        return float(out)
    return out


def fold_octave(cents):
    """Fold cents into the range [0, 1200). NaN stays NaN."""
    c = np.asarray(cents, dtype=float)
    out = np.mod(c, OCTAVE)
    if out.ndim == 0:
        return float(out)
    return out


def fold_to_reference(cents, reference_cents):
    """Shift ``cents`` by whole octaves so it lands within 600 cents of ``reference_cents``.

    Used before comparing two singers: if I sing an octave below the teacher, my
    curve is moved up by 1200 so the shapes can be compared. Both arguments may be
    arrays of the same shape, or ``reference_cents`` may be a scalar.
    """
    c = np.asarray(cents, dtype=float)
    r = np.asarray(reference_cents, dtype=float)
    shift = np.round((r - c) / OCTAVE) * OCTAVE
    out = c + shift
    if out.ndim == 0:
        return float(out)
    return out


def pitch_histogram(cents, bin_cents: float = 10.0, fold: bool = True, smooth_bins: int = 3):
    """Histogram of a pitch curve in cents.

    Returns ``(bin_centers, counts)``. With ``fold=True`` all values are folded into
    one octave [0, 1200) first, so notes sung in different octaves add up. NaN values
    (unvoiced frames) are ignored. ``smooth_bins`` applies a circular moving average
    to make peaks easier to find; use 1 for no smoothing.
    """
    c = np.asarray(cents, dtype=float)
    c = c[np.isfinite(c)]
    if fold:
        c = fold_octave(c)
        lo, hi = 0.0, OCTAVE
    else:
        if c.size == 0:
            return np.array([]), np.array([])
        lo = np.floor(c.min() / bin_cents) * bin_cents
        hi = np.ceil(c.max() / bin_cents) * bin_cents + bin_cents
    edges = np.arange(lo, hi + bin_cents / 2, bin_cents)
    counts, _ = np.histogram(c, bins=edges)
    centers = edges[:-1] + bin_cents / 2
    counts = counts.astype(float)
    if smooth_bins > 1 and counts.size:
        kernel = np.ones(smooth_bins) / smooth_bins
        if fold:
            padded = np.concatenate([counts[-smooth_bins:], counts, counts[:smooth_bins]])
            counts = np.convolve(padded, kernel, mode="same")[smooth_bins:-smooth_bins]
        else:
            counts = np.convolve(counts, kernel, mode="same")
    return centers, counts


def estimate_tonic(f0_hz, method: str = "histogram", final_seconds: float = 1.5,
                   hop_seconds: float | None = None) -> float:
    """Estimate the tonic from a pitch curve in Hz (NaN = unvoiced).

    ``method="histogram"``: the most common folded pitch class, placed in the octave
    closest to the median of the sung pitches. This picks the shahed (the most
    repeated note), which is what we usually want as the reference.

    ``method="final"``: the median pitch of the last ``final_seconds`` of voiced
    audio, which is usually the finalis (ist) of the phrase. Needs ``hop_seconds``.
    """
    f0 = np.asarray(f0_hz, dtype=float)
    voiced = f0[np.isfinite(f0) & (f0 > 0)]
    if voiced.size == 0:
        raise ValueError("no voiced frames to estimate a tonic from")

    if method == "final":
        if hop_seconds is None:
            raise ValueError("hop_seconds is required for method='final'")
        n = max(1, int(round(final_seconds / hop_seconds)))
        return float(np.median(voiced[-n:]))

    if method != "histogram":
        raise ValueError(f"unknown tonic method: {method}")

    ref = 110.0
    cents = hz_to_cents(voiced, ref)
    centers, counts = pitch_histogram(cents, bin_cents=5.0, fold=True, smooth_bins=5)
    peak = float(centers[int(np.argmax(counts))])
    # Refine: mean of the folded values within 25 cents of the peak (circular).
    folded = fold_octave(cents)
    diff = (folded - peak + 600.0) % OCTAVE - 600.0
    near = np.abs(diff) < 25.0
    if near.any():
        peak = peak + float(np.mean(diff[near]))
    # Place it in the octave nearest the median of what was sung.
    median_cents = float(np.median(cents))
    candidate = fold_to_reference(peak, median_cents)
    return float(cents_to_hz(candidate, ref))


def octave_shift(my_cents, teacher_cents, min_points: int = 20) -> float:
    """Whole octaves to add to my curve so its median lands nearest the teacher's median.

    Returns 0 until there are at least ``min_points`` voiced values on both sides.
    """
    mine = np.asarray(my_cents, dtype=float)
    theirs = np.asarray(teacher_cents, dtype=float)
    mine = mine[np.isfinite(mine)]
    theirs = theirs[np.isfinite(theirs)]
    if mine.size < min_points or theirs.size < min_points:
        return 0.0
    return float(np.round((np.median(theirs) - np.median(mine)) / OCTAVE) * OCTAVE)
