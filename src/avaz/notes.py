"""Note lanes and note blocks: a simpler picture of a pitch curve.

Instead of the full curve with every wobble, the chart can show one horizontal
lane per note of the dastgah and light up a block in the lane while the voice
stays on that note, like a piano roll. Each frame is given to the nearest scale
note; runs of frames on the same note become one block. That shows which note
is being sung, and for how long, at a glance. The detailed curve can still be
drawn thinly on top.
"""

from __future__ import annotations

import numpy as np


def lane_edges(centers) -> list[tuple[float, float, float]]:
    """``(center, low, high)`` per note: each lane reaches halfway to its neighbours.

    The outermost lanes get the same half width as their only neighbour.
    """
    c = np.sort(np.asarray(centers, dtype=float))
    if c.size == 0:
        return []
    if c.size == 1:
        return [(float(c[0]), float(c[0] - 50), float(c[0] + 50))]
    mids = (c[1:] + c[:-1]) / 2
    lows = np.concatenate([[c[0] - (mids[0] - c[0])], mids])
    highs = np.concatenate([mids, [c[-1] + (c[-1] - mids[-1])]])
    return [(float(a), float(lo), float(hi)) for a, lo, hi in zip(c, lows, highs)]


def note_blocks(times, cents, centers, min_seconds: float = 0.05, max_gap: float = 0.03):
    """Blocks of time spent on one scale note.

    Returns a dict of arrays ``t0``, ``t1``, ``center`` (the note, in cents) and
    ``dev`` (median deviation of the voice from that note, in cents). A block
    survives a gap in the voice of up to ``max_gap`` seconds; blocks shorter than
    ``min_seconds`` are dropped, so a slide through a note does not flash a block.
    """
    t = np.asarray(times, dtype=float)
    x = np.asarray(cents, dtype=float)
    c = np.sort(np.asarray(centers, dtype=float))
    empty = {k: np.zeros(0) for k in ("t0", "t1", "center", "dev")}
    if t.size == 0 or c.size == 0:
        return empty
    hop = float(np.median(np.diff(t))) if t.size > 1 else 0.0
    voiced = np.isfinite(x)
    idx = np.full(t.size, -1)
    if voiced.any():
        d = np.abs(x[voiced, None] - c[None, :])
        idx[voiced] = np.argmin(d, axis=1)

    t0s, t1s, cs, devs = [], [], [], []
    start = last = note = -1             # first and last frame index of the open block

    def close():
        if t[last] + hop - t[start] >= min_seconds:
            seg = slice(start, last + 1)
            on = idx[seg] == note
            t0s.append(t[start]); t1s.append(t[last] + hop); cs.append(c[note])
            devs.append(float(np.median(x[seg][on] - c[note])))

    for i in range(t.size):
        k = idx[i]
        if k < 0:
            if start >= 0 and t[i] - t[last] > max_gap:
                close()
                start = -1
            continue
        if start >= 0 and k == note:
            last = i
            continue
        if start >= 0:
            close()
        start, last, note = i, i, k
    if start >= 0:
        close()
    if not t0s:
        return empty
    return {"t0": np.array(t0s), "t1": np.array(t1s), "center": np.array(cs), "dev": np.array(devs)}


def break_jumps(times, cents, max_jump: float = 500.0):
    """Gap the line where it jumps more than ``max_jump`` cents in one frame.

    A voice cannot move that far in a few milliseconds; such jumps are the
    detector slipping an octave for a frame, and drawn as lines they look like
    tall spikes.
    """
    cents = np.array(cents, dtype=float)
    if cents.size > 1:
        jump = np.abs(np.diff(cents)) > max_jump
        cents[1:][jump] = np.nan
    return times, cents
