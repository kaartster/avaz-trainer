"""Plain-words feedback for a beginner: "sing higher at 0:12", "hold the long notes longer".

The score (:mod:`compare`) is in cents and percentages, which only mean something
to a trained ear. This module turns it into a few short sentences, each with a
direction (sing higher, sing lower) and, where it applies, the stretch of time it
is about, so the practice window can also mark that spot on the chart.

It also decides the live hint while I sing: is my voice right now on one of the
teacher's notes around this moment, above them, or below them.

Two levels:

* **gentle** (:func:`gentle_feedback`, the default): only the teacher's long,
  steady notes are judged, a note counts as hit within a quarter tone, fast
  ornaments are left out. It says how many long notes I hit (with stars),
  whether that is better than my last try, and gives one tip for next time,
  the most general one first. Only notes that were really off (half a tone or
  more) are marked on the chart.
* **detailed** (:func:`attempt_feedback`): every frame within 25 cents, up to
  three problem spots with arrows, and a line per kind of problem.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .keys import scale_note_name

HIGHER, OK, LOWER = 1, 0, -1

DEFAULTS = {
    "key_offset_cents": 30.0,     # whole stretch off by more than this: one "sing higher" hint
    "fast_ratio": 0.85,           # my singing time / teacher's below this: "too fast"
    "slow_ratio": 1.2,            # above this: "too slow"
    "max_spots": 3,               # at most this many problem spots per attempt
    "live_tolerance_cents": 30.0,  # live hint: this close to a teacher note counts as on it
    "live_window_seconds": 0.3,   # live hint: teacher notes this far around "now" count
}


GENTLE_DEFAULTS = {
    "hit_cents": 50.0,            # a long note this close to the teacher's counts as hit
    "very_off_cents": 100.0,      # only notes this far off are marked on the chart
    "overall_cents": 35.0,        # most notes off in one direction by this: an overall tip
    "min_note_seconds": 0.25,     # teacher notes held at least this long are judged
    "max_marks": 2,               # at most this many marked notes per attempt
    "live_tolerance_cents": 60.0,  # live hint only when this far from the teacher
    "live_hold_seconds": 0.5,     # ... for at least this long
}


@dataclass
class Hint:
    kind: str                  # "overall", "key", "spot", "timing", "progress", "tip", "mark"
    text: str
    direction: int = OK        # HIGHER: sing higher, LOWER: sing lower, OK: neither
    start: float | None = None  # seconds, for "spot" hints
    end: float | None = None


def amount_words(cents: float) -> str:
    """How far off, in words. A quarter tone is 50 cents, a half tone 100."""
    c = abs(float(cents))
    if c < 35:
        return "a little"
    if c < 75:
        return "about a quarter tone"
    if c < 150:
        return "about half a tone"
    return "a lot"


def clock(seconds: float) -> str:
    """``72.4`` -> ``"1:12"``."""
    s = max(0, int(seconds))           # like a media player: 0:10 until 0:11 begins
    return f"{s // 60}:{s % 60:02d}"


def _settings(cfg: dict | None) -> dict:
    out = dict(DEFAULTS)
    out.update({k: v for k, v in (cfg or {}).items() if v is not None})
    return out


def _overall(pct: float) -> str:
    if pct >= 85:
        return "✓ Very good: almost every note in tune"
    if pct >= 65:
        return "✓ Good: most notes in tune"
    if pct >= 40:
        return "About half of the notes in tune. Keep going"
    return "Many notes were off. Listen once more (R) and try again"


def _note_at(result, start: float, end: float, name_tonic_hz: float | None) -> str:
    """Name of the teacher's note during ``start..end`` (reference time), or ""."""
    if not name_tonic_hz or result.ref_times is None or result.ref_cents is None:
        return ""
    t, c = np.asarray(result.ref_times), np.asarray(result.ref_cents)
    m = (t >= start) & (t <= end) & np.isfinite(c)
    if not m.any():
        return ""
    return scale_note_name(name_tonic_hz, float(np.median(c[m])))


def attempt_feedback(result, name_tonic_hz: float | None = None, time_offset: float = 0.0,
                     cfg: dict | None = None) -> list[Hint]:
    """Short sentences about one attempt, most general first.

    ``result`` is a :class:`compare.ScoreResult`. ``name_tonic_hz`` names the notes
    (the tonic I sing in). ``time_offset`` is added to the reference times so the
    spots are given in song time rather than from the start of the stretch.
    """
    s = _settings(cfg)
    if not result.n_pairs:
        return [Hint("overall", "I could not hear enough singing to compare. Try again a bit louder")]
    hints = [Hint("overall", _overall(result.pct_within))]

    key = result.key_offset
    if np.isfinite(key) and abs(key) >= s["key_offset_cents"]:
        if key < 0:
            hints.append(Hint("key", f"↑ Overall you were {amount_words(key)} too low: sing higher",
                              HIGHER))
        else:
            hints.append(Hint("key", f"↓ Overall you were {amount_words(key)} too high: sing lower",
                              LOWER))

    spots = sorted(result.worst[:int(s["max_spots"])], key=lambda sec: sec.start)
    for sec in spots:
        when = clock(sec.start + time_offset)
        note = _note_at(result, sec.start, sec.end, name_tonic_hz)
        where = f"At {when} ({note})" if note else f"At {when}"
        steady = abs(sec.mean_dev) >= 0.6 * sec.mean_abs_dev
        if not steady:
            hints.append(Hint("spot", f"~ {where}: wobbly, hold the note steadier", OK,
                              sec.start + time_offset, sec.end + time_offset))
        elif sec.mean_dev < 0:
            hints.append(Hint("spot", f"↑ {where}: {amount_words(sec.mean_dev)} too low, sing higher",
                              HIGHER, sec.start + time_offset, sec.end + time_offset))
        else:
            hints.append(Hint("spot", f"↓ {where}: {amount_words(sec.mean_dev)} too high, sing lower",
                              LOWER, sec.start + time_offset, sec.end + time_offset))

    ratio = result.timing_ratio
    if ratio and ratio < s["fast_ratio"]:
        hints.append(Hint("timing", "⏱ You were faster than the teacher: hold the long notes longer"))
    elif ratio > s["slow_ratio"]:
        hints.append(Hint("timing", "⏱ You were slower than the teacher: move on a little sooner"))
    return hints


def live_direction(my_cents, teacher_cents, tolerance: float = DEFAULTS["live_tolerance_cents"],
                   min_points: int = 3) -> int | None:
    """Live hint: HIGHER, LOWER or OK, or None when there is nothing to compare.

    ``my_cents`` is my last few pitch values (a median smooths the jitter).
    ``teacher_cents`` is the teacher's pitch in a short window around the same
    moment. A window rather than one instant, because I am never exactly in time
    with the teacher: being on any of the teacher's notes around now counts.
    """
    mine = np.asarray(my_cents, dtype=float)
    mine = mine[np.isfinite(mine)]
    teacher = np.asarray(teacher_cents, dtype=float)
    teacher = teacher[np.isfinite(teacher)]
    if mine.size < min_points or teacher.size == 0:
        return None
    me = float(np.median(mine))
    nearest = teacher[np.argmin(np.abs(teacher - me))]
    diff = float(nearest - me)
    if abs(diff) <= tolerance:
        return OK
    return HIGHER if diff > 0 else LOWER


# ---------------------------------------------------------------- gentle level

@dataclass
class HeldNote:
    start: float               # seconds in the reference timeline
    end: float
    teacher: float             # the teacher's note, cents (median)
    mine: float                # what I sang for it, cents (median), NaN if I was silent
    steady: bool = True        # False: I never held a pitch there, only slid or wobbled

    @property
    def dev(self) -> float:
        return self.mine - self.teacher

    def hit(self, tolerance: float) -> bool:
        return self.steady and abs(self.dev) <= tolerance


def _candidates(t, a, start: float, end: float, teacher: float, k: int, window: float,
                step: float, steady_cents: float, cents_per_second: float) -> list[tuple]:
    """Steady stretches of my voice that could be my answer to one teacher note.

    Each is ``(cost, gap, window_start, window_end, median_cents)``.
    """
    idx = np.nonzero((t >= start - window) & (t < end + window))[0]
    out = []
    for j in range(idx.size - k + 1):
        seg = a[idx[j:j + k]]
        seg = seg[np.isfinite(seg)]
        if seg.size < 0.8 * k:
            continue
        lo, hi = np.percentile(seg, [10, 90])
        if hi - lo > steady_cents:
            continue                        # sliding or wobbling, not holding a note
        m = float(np.median(seg))
        ws, we = float(t[idx[j]]), float(t[idx[j + k - 1]] + step)
        gap = max(0.0, ws - end, start - we)         # 0 when it overlaps the teacher's note
        out.append((abs(m - teacher) + cents_per_second * gap, gap, ws, we, m))
    return out


def _extent(t, a, ws: float, we: float, m: float, tol: float, max_gap: float) -> tuple[float, float]:
    """The whole held note of mine around ``ws..we``: grow while my pitch stays within
    ``tol`` cents of ``m`` (silences up to ``max_gap`` bridged)."""
    step = float(np.median(np.diff(t))) if t.size > 1 else 0.02
    on = np.isfinite(a) & (np.abs(a - m) <= tol)
    i = int(np.searchsorted(t, ws))
    j = int(np.searchsorted(t, we)) - 1
    gap_bins = int(round(max_gap / step))
    while True:
        k = next((i - d for d in range(1, gap_bins + 2) if i - d >= 0 and on[i - d]), None)
        if k is None:
            break
        i = k
    while True:
        k = next((j + d for d in range(1, gap_bins + 2) if j + d < t.size and on[j + d]), None)
        if k is None:
            break
        j = k
    return float(min(t[i], ws)), float(max(t[j] + step, we))


def held_notes(times, ref_cents, att_cents, min_seconds: float = 0.25, spread: float = 60.0,
               max_gap: float = 0.06, window: float = 0.5, hold_fraction: float = 0.3,
               steady_cents: float = 80.0, cents_per_second: float = 300.0) -> list[HeldNote]:
    """The teacher's long, steady notes and what I sang for each of them.

    A note is a run of the teacher's pitch that stays within ``spread`` cents of
    where it started, for at least ``min_seconds`` (gaps up to ``max_gap`` are
    bridged). Fast ornaments keep jumping out of that band, so they never make a
    note and are not judged.

    ``att_cents`` is my pitch on the same time grid (see :func:`stretch_onto`).
    My answer to a note is looked for up to ``window`` seconds before and after
    it, because my timing drifts: I hold notes shorter than the teacher. Every
    steady stretch of my voice there, as long as ``hold_fraction`` of the note and
    staying within ``steady_cents``, is a candidate. It costs how far it is from
    the teacher's note in cents, plus ``cents_per_second`` for each second it lies
    outside the note. The cheapest pairs are settled first, and a stretch of my
    voice answers only one note: so my own note at the right moment is never
    taken by a neighbouring note that merely sounds close, and a wrong note cannot
    hide behind one either. (Only when everything I held near a note already
    answered another one is it shared.)

    Holding the right note for about a third of its length, a little early or
    late, counts; sliding through it does not (``steady`` is then False and
    ``mine`` is the median of what I sang around it). With fewer voiced values
    than that in the window, ``mine`` is NaN (not sung).
    """
    t = np.asarray(times, dtype=float)
    r = np.asarray(ref_cents, dtype=float)
    a = np.asarray(att_cents, dtype=float)
    step = float(np.median(np.diff(t))) if t.size > 1 else 0.02

    runs: list[list[int]] = []
    run: list[int] = []
    for i in np.nonzero(np.isfinite(r))[0]:
        if run:
            anchor = float(np.median(r[run[:5]]))
            if abs(r[i] - anchor) <= spread and t[i] - t[run[-1]] <= max_gap + step / 2:
                run.append(i)
                continue
            runs.append(run)
        run = [i]
    if run:
        runs.append(run)
    runs = [rn for rn in runs if t[rn[-1]] + step - t[rn[0]] >= min_seconds]

    notes, sizes, options = [], [], []
    for rn in runs:
        start, end = float(t[rn[0]]), float(t[rn[-1]] + step)
        teacher = float(np.median(r[rn]))
        k = max(3, int(round(hold_fraction * len(rn))))
        notes.append(HeldNote(start, end, teacher, np.nan))
        sizes.append(k)
        options.append(_candidates(t, a, start, end, teacher, k, window, step,
                                   steady_cents, cents_per_second))

    # Cheapest pairs first; a stretch of my voice already used cannot answer again.
    taken: list[tuple[float, float]] = []
    pairs = sorted((c[0], c[1], n, c) for n, cands in enumerate(options) for c in cands)
    done = set()
    for _, _, n, (_, _, ws, we, m) in pairs:
        if n in done or any(ws < b - 1e-9 and we > a_ + 1e-9 for a_, b in taken):
            continue
        notes[n].mine = m
        done.add(n)
        taken.append(_extent(t, a, ws, we, m, min(steady_cents / 2, 30.0), max_gap))

    for n, note in enumerate(notes):
        if n in done:
            continue
        if options[n]:
            # I held something here, but it already answered a neighbouring note
            # (for example two of the teacher's notes sung as one): use it anyway.
            note.mine = min(options[n])[4]
            continue
        near = a[(t >= note.start - window) & (t < note.end + window)]
        near = near[np.isfinite(near)]
        if near.size >= sizes[n]:
            note.mine = float(np.median(near))
            note.steady = False
    return notes


def _gentle(cfg: dict | None) -> dict:
    out = dict(GENTLE_DEFAULTS)
    out.update({k: v for k, v in ((cfg or {}).get("gentle") or {}).items() if v is not None})
    return out


def stretch_onto(ref_times, ref_cents, att_times, att_cents) -> np.ndarray:
    """My pitch on the teacher's time grid, stretched evenly so the first and last
    sung moments meet.

    That evens out singing a bit faster or slower overall, but unlike DTW it
    cannot pair a wrong note with some other moment where the teacher happened to
    sing that pitch, so a wrong note stays wrong. NaN where I was silent.
    """
    rt, rc = np.asarray(ref_times, dtype=float), np.asarray(ref_cents, dtype=float)
    at, ac = np.asarray(att_times, dtype=float), np.asarray(att_cents, dtype=float)
    out = np.full(rt.size, np.nan)
    rv, av = np.nonzero(np.isfinite(rc))[0], np.nonzero(np.isfinite(ac))[0]
    if rv.size < 2 or av.size < 2 or at[av[-1]] <= at[av[0]]:
        return out
    r0, r1, a0, a1 = rt[rv[0]], rt[rv[-1]], at[av[0]], at[av[-1]]
    mapped = r0 + (at - a0) * (r1 - r0) / (a1 - a0)        # my times on the teacher's clock
    step = float(np.median(np.diff(rt))) if rt.size > 1 else 0.02
    idx = np.round((mapped - rt[0]) / step).astype(int)
    ok = np.isfinite(ac) & (idx >= 0) & (idx < rt.size)
    # Several of my bins can land on one of the teacher's: average them.
    sums = np.zeros(rt.size)
    counts = np.zeros(rt.size)
    np.add.at(sums, idx[ok], ac[ok])
    np.add.at(counts, idx[ok], 1)
    out[counts > 0] = sums[counts > 0] / counts[counts > 0]
    # Stretching a faster attempt spreads its bins apart: fill the small holes that
    # leaves (up to 3 bins between sung values) so a held note stays one piece.
    filled = np.nonzero(counts > 0)[0]
    if filled.size > 1:
        holes = np.nonzero(np.isnan(out))[0]
        holes = holes[(holes > filled[0]) & (holes < filled[-1])]
        nxt = filled[np.searchsorted(filled, holes)]
        prv = filled[np.searchsorted(filled, holes) - 1]
        small = nxt - prv <= 4
        out[holes[small]] = np.interp(holes[small], filled, out[filled])
    return out


def _sung_notes(result, g: dict) -> list[HeldNote]:
    if result.ref_times is None or result.att_times is None:
        return []
    mine = stretch_onto(result.ref_times, result.ref_cents, result.att_times, result.att_cents)
    return [n for n in held_notes(result.ref_times, result.ref_cents, mine,
                                  g["min_note_seconds"]) if np.isfinite(n.mine)]


def note_hits(result, cfg: dict | None = None) -> tuple[int, int]:
    """``(hit, sung)``: long notes I hit, out of the long notes I sang at all."""
    g = _gentle(cfg)
    notes = _sung_notes(result, g)
    return sum(n.hit(g["hit_cents"]) for n in notes), len(notes)


def stars(fraction: float) -> str:
    n = int(np.clip(round(fraction * 5), 1, 5))
    return "★" * n + "☆" * (5 - n)


def _praise(fraction: float) -> str:
    if fraction >= 0.9:
        return "Excellent!"
    if fraction >= 0.7:
        return "Well done!"
    if fraction >= 0.5:
        return "Good effort!"
    return "Keep going, every try makes it easier."


def gentle_feedback(result, name_tonic_hz: float | None = None, time_offset: float = 0.0,
                    cfg: dict | None = None, previous: tuple[int, int] | None = None) -> list[Hint]:
    """Encouraging feedback: stars, progress, one tip, and marks only where it was very off.

    ``previous`` is ``(hit, sung)`` from my last try of the same stretch; a better
    result is celebrated, a worse one is not mentioned.
    """
    s, g = _settings(cfg), _gentle(cfg)
    if not result.n_pairs:
        return [Hint("overall", "I could not hear enough singing to compare. Try again a bit louder")]
    notes = _sung_notes(result, g)
    hints = []
    if notes:
        hit = sum(n.hit(g["hit_cents"]) for n in notes)
        frac = hit / len(notes)
        hints.append(Hint("overall", f"{stars(frac)}  {_praise(frac)}  You hit {hit} of "
                                     f"{len(notes)} long notes"))
        if previous and previous[1] and frac > previous[0] / previous[1] + 1e-9:
            hints.append(Hint("progress", f"Better than your last try ({previous[0]} of "
                                          f"{previous[1]} before) 🎉"))
        held = [n.dev for n in notes if n.steady]
        overall = float(np.median(held)) if held else 0.0
    else:
        # A stretch of only fast ornaments: judge it as a whole, gently.
        dev = np.asarray(result.dev_on_ref if result.dev_on_ref is not None else [], dtype=float)
        dev = dev[np.isfinite(dev)]
        frac = float((np.abs(dev) <= g["hit_cents"]).mean()) if dev.size else 0.0
        hints.append(Hint("overall", f"{stars(frac)}  {_praise(frac)}  This stretch is fast, "
                                     f"{100 * frac:.0f}% of it was close to the teacher"))
        overall = result.key_offset if np.isfinite(result.key_offset) else 0.0

    # Notes off by a lot even after the overall direction is taken into account.
    shift = overall if abs(overall) >= g["overall_cents"] else 0.0
    very_off = sorted((n for n in notes if n.steady and abs(n.dev - shift) >= g["very_off_cents"]),
                      key=lambda n: abs(n.dev - shift), reverse=True)[:int(g["max_marks"])]

    def where(n):
        name = scale_note_name(name_tonic_hz, n.teacher) if name_tonic_hz else ""
        when = clock(n.start + time_offset)
        return f"the note at {when} ({name})" if name else f"the note at {when}"

    tip = None
    if shift:
        low = shift < 0
        tip = Hint("tip", f"Next try: aim a bit {'higher' if low else 'lower'} overall, most "
                          f"notes were {amount_words(shift)} {'low' if low else 'high'}",
                   HIGHER if low else LOWER)
    elif very_off:
        n = very_off[0]
        low = n.dev < 0
        tip = Hint("tip", f"Next try: {where(n)} was {amount_words(n.dev)} too "
                          f"{'low' if low else 'high'}, reach a bit {'higher' if low else 'lower'}",
                   HIGHER if low else LOWER)
    elif notes and sum(not n.steady for n in notes) * 2 >= len(notes):
        tip = Hint("tip", "Next try: on the long notes, settle on one pitch and hold it steady")
    elif result.timing_ratio and result.timing_ratio < s["fast_ratio"]:
        tip = Hint("tip", "Next try: hold the long notes a little longer, like the teacher")
    elif result.timing_ratio > s["slow_ratio"]:
        tip = Hint("tip", "Next try: keep moving, you were a bit slower than the teacher")
    if tip:
        hints.append(tip)
    for n in very_off:
        hints.append(Hint("mark", "", HIGHER if n.dev - shift < 0 else LOWER,
                          n.start + time_offset, n.end + time_offset))
    return hints


class LiveHold:
    """Shows a live hint only once it has held for a while, so the screen stays calm.

    Feed it the live direction every frame with :meth:`update`; it returns the
    direction to show (HIGHER or LOWER) or None. Being on the note shows nothing.
    """

    def __init__(self, hold_seconds: float = GENTLE_DEFAULTS["live_hold_seconds"]):
        self.hold = float(hold_seconds)
        self._dir: int | None = None
        self._since = 0.0

    def update(self, direction: int | None, now: float) -> int | None:
        if direction not in (HIGHER, LOWER):
            self._dir = None
            return None
        if direction != self._dir:
            self._dir, self._since = direction, now
        return direction if now - self._since >= self.hold else None
