"""Static matplotlib plots for offline analysis (curve over time, folded histogram)."""

from __future__ import annotations

import numpy as np

from .cents import OCTAVE
from .pitch_offline import PitchCurve
from .scales import Scale, find_histogram_peaks


def _guide_lines(ax, scale: Scale | None, lo: float, hi: float, colors: dict):
    if scale is None:
        ax.axhline(0, color=colors.get("tonic", "#2ca02c"), lw=1.2)
        return
    for c, label in scale.positions_in_range(lo, hi):
        is_tonic = abs(c % OCTAVE) < 1e-6
        ax.axhline(c, color=colors.get("tonic" if is_tonic else "guide", "#888888"),
                   lw=1.2 if is_tonic else 0.6, ls="-" if is_tonic else "--", alpha=0.8)
        ax.text(0.0, c, f" {label}", va="bottom", ha="left", fontsize=7,
                color=colors.get("guide", "#888888"))


def plot_curve(curve: PitchCurve, scale: Scale | None = None, title: str = "",
               colors: dict | None = None, show: bool = True, save_path=None):
    import matplotlib.pyplot as plt

    colors = colors or {}
    fig, ax = plt.subplots(figsize=(14, 6))
    ax.plot(curve.times, curve.cents, color=colors.get("teacher", "#1f77b4"), lw=1.0)
    finite = curve.cents[np.isfinite(curve.cents)]
    if finite.size:
        lo = float(np.floor((finite.min() - 100) / 100) * 100)
        hi = float(np.ceil((finite.max() + 100) / 100) * 100)
    else:
        lo, hi = -700.0, 1900.0
    _guide_lines(ax, scale, lo, hi, colors)
    ax.set_ylim(lo, hi)
    ax.set_xlim(0, curve.duration)
    ax.set_xlabel("time (s)")
    ax.set_ylabel(f"cents relative to tonic ({curve.tonic_hz:.1f} Hz)")
    ax.set_title(title or curve.source)
    ax.grid(True, axis="x", alpha=0.3)
    fig.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=120)
    if show:
        plt.show()
    return fig


def plot_histogram(centers, counts, suggested=None, scale: Scale | None = None,
                   title: str = "", colors: dict | None = None, show: bool = True,
                   save_path=None):
    import matplotlib.pyplot as plt

    colors = colors or {}
    fig, ax = plt.subplots(figsize=(12, 5))
    width = float(centers[1] - centers[0]) if len(centers) > 1 else 10.0
    ax.bar(centers, counts, width=width, color=colors.get("teacher", "#1f77b4"), alpha=0.8)
    if scale is not None:
        for p, label in zip(scale.positions, scale.labels):
            if 0 <= p <= OCTAVE:
                ax.axvline(p, color=colors.get("guide", "#888888"), ls="--", lw=0.8)
                ax.text(p, ax.get_ylim()[1] * 0.98, label, rotation=90, va="top", ha="right",
                        fontsize=8, color=colors.get("guide", "#888888"))
    for p in (suggested or []):
        ax.axvline(p, color=colors.get("mine", "#d62728"), lw=1.2, alpha=0.9)
        ax.text(p, ax.get_ylim()[1] * 0.5, f"{p:.0f}", rotation=90, va="center", ha="right",
                fontsize=8, color=colors.get("mine", "#d62728"))
    ax.set_xlim(0, OCTAVE)
    ax.set_xticks(np.arange(0, OCTAVE + 1, 100))
    ax.set_xlabel("cents above tonic (folded into one octave)")
    ax.set_ylabel("frames")
    ax.set_title(title)
    fig.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=120)
    if show:
        plt.show()
    return fig


def plot_segmentation(y, sr, phrases, curve=None, title: str = "", colors: dict | None = None,
                      show: bool = True, save_path=None):
    """Loudness envelope and pitch curve with the detected phrases shaded."""
    import matplotlib.pyplot as plt
    from .slicer import rms_db

    colors = colors or {}
    times, db = rms_db(y, sr)
    fig, axes = plt.subplots(2 if curve is not None else 1, 1, figsize=(16, 7), sharex=True,
                             squeeze=False)
    ax = axes[0, 0]
    ax.plot(times, db, lw=0.5, color="black")
    ax.set_ylabel("loudness (dBFS)")
    ax.set_ylim(max(-90, float(np.min(db)) - 5), 0)
    for ph in phrases:
        for a in axes[:, 0]:
            a.axvspan(ph.start, ph.end, color=colors.get("teacher", "#1f77b4"), alpha=0.15)
        ax.text(ph.start, -3, ph.label, fontsize=7, va="top", rotation=90)
    if curve is not None:
        ax2 = axes[1, 0]
        ax2.plot(curve.times, curve.cents, lw=0.6, color=colors.get("teacher", "#1f77b4"))
        ax2.axhline(0, color=colors.get("tonic", "#2ca02c"), lw=1)
        ax2.set_ylabel(f"cents vs {curve.tonic_hz:.1f} Hz")
        finite = curve.cents[np.isfinite(curve.cents)]
        if finite.size:
            ax2.set_ylim(np.percentile(finite, 0.5) - 100, np.percentile(finite, 99.5) + 100)
    axes[-1, 0].set_xlabel("time (s)")
    axes[0, 0].set_title(title)
    fig.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=120)
    if show:
        plt.show()
    return fig


def plot_score(result, title: str = "", scale=None, colors: dict | None = None,
               show: bool = True, save_path=None):
    """Reference curve, attempt warped onto it, deviation track, worst sections shaded."""
    import matplotlib.pyplot as plt

    colors = colors or {}
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True,
                             gridspec_kw={"height_ratios": [3, 1]})
    ax = axes[0]
    ax.plot(result.ref_times, result.ref_cents, color=colors.get("teacher", "#1f77b4"), lw=1.8,
            label="teacher")
    ax.plot(result.ref_times, result.att_on_ref, color=colors.get("mine", "#d62728"), lw=1.4,
            label="me (aligned)")
    finite = np.concatenate([result.ref_cents[np.isfinite(result.ref_cents)],
                             result.att_on_ref[np.isfinite(result.att_on_ref)]])
    if finite.size:
        lo = float(np.floor((finite.min() - 150) / 100) * 100)
        hi = float(np.ceil((finite.max() + 150) / 100) * 100)
    else:
        lo, hi = -700.0, 1900.0
    _guide_lines(ax, scale, lo, hi, colors)
    ax.set_ylim(lo, hi)
    for i, sec in enumerate(result.worst):
        ax.axvspan(sec.start, sec.end, color="#e74c3c", alpha=0.18)
        ax.text(sec.start, hi - 40, f"{i + 1}: {sec.mean_dev:+.0f}", fontsize=8, color="#c0392b",
                va="top")
    ax.set_ylabel("cents relative to own tonic")
    ax.legend(loc="upper right")
    ax.set_title(title or f"within {result.tolerance:.0f} cents: {result.pct_within:.0f}%   "
                          f"mean deviation {result.mad:.0f} cents")

    ax2 = axes[1]
    ax2.axhspan(-result.tolerance, result.tolerance, color="#2ecc71", alpha=0.15)
    ax2.axhline(0, color="#2ecc71", lw=1)
    ax2.plot(result.ref_times, result.dev_on_ref, color=colors.get("mine", "#d62728"), lw=1.2)
    for sec in result.worst:
        ax2.axvspan(sec.start, sec.end, color="#e74c3c", alpha=0.18)
    span = np.nanmax(np.abs(result.dev_on_ref)) if np.isfinite(result.dev_on_ref).any() else 100
    ax2.set_ylim(-max(100, span + 20), max(100, span + 20))
    ax2.set_ylabel("me - teacher (cents)")
    ax2.set_xlabel("reference time (s)")
    fig.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=120)
    if show:
        plt.show()
    return fig


def plot_history(rows: list[dict], title: str = "", show: bool = True, save_path=None):
    """Percent within tolerance and mean deviation per attempt, in recording order."""
    import matplotlib.pyplot as plt
    from datetime import datetime

    if not rows:
        return None
    xs = []
    for r in rows:
        try:
            xs.append(datetime.strptime(r["recorded_at"], "%Y%m%d_%H%M%S"))
        except (KeyError, ValueError):
            xs.append(len(xs))
    pct = [r["pct_within"] for r in rows]
    mad = [r["mad"] for r in rows]
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(xs, pct, "o-", color="#2ecc71", label="% within tolerance")
    ax.set_ylim(0, 100)
    ax.set_ylabel("% within tolerance", color="#27ae60")
    ax2 = ax.twinx()
    ax2.plot(xs, mad, "s--", color="#d62728", label="mean deviation (cents)")
    ax2.set_ylabel("mean deviation (cents)", color="#d62728")
    ax2.set_ylim(0, max(60, max(mad) + 10))
    for x, r in zip(xs, rows):
        ax.annotate(f"x{r.get('speed', 1) or 1:.1f}", (x, r["pct_within"]), textcoords="offset points",
                    xytext=(0, 6), ha="center", fontsize=7, color="#555555")
    ax.set_title(title)
    fig.autofmt_xdate()
    fig.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=120)
    if show:
        plt.show()
    return fig
