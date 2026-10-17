import numpy as np
import pytest

from avaz.compare import ScoreResult, Section, score_curves
from avaz.feedback import (HIGHER, LOWER, OK, amount_words, attempt_feedback, clock,
                           live_direction)
from avaz.pitch_offline import PitchCurve


def result(pct=90.0, key=0.0, timing=1.0, worst=(), n_pairs=100, ref_times=None, ref_cents=None):
    return ScoreResult(mad=10.0, median_abs=8.0, pct_within=pct, tolerance=25.0, octave_shift=0.0,
                       timing_ratio=timing, n_pairs=n_pairs, worst=list(worst), key_offset=key,
                       ref_times=ref_times, ref_cents=ref_cents)


def test_amount_words_and_clock():
    assert amount_words(20) == "a little"
    assert amount_words(-50) == "about a quarter tone"
    assert amount_words(100) == "about half a tone"
    assert amount_words(300) == "a lot"
    assert clock(72.9) == "1:12"
    assert clock(5) == "0:05"


def test_good_attempt_gets_one_happy_line():
    hints = attempt_feedback(result(pct=92))
    assert [h.kind for h in hints] == ["overall"]
    assert "Very good" in hints[0].text


def test_no_singing_says_so_and_nothing_else():
    hints = attempt_feedback(result(n_pairs=0))
    assert len(hints) == 1 and "could not hear" in hints[0].text


def test_overall_too_low_says_sing_higher():
    hints = attempt_feedback(result(pct=50, key=-60))
    key = [h for h in hints if h.kind == "key"][0]
    assert key.direction == HIGHER
    assert "too low" in key.text and "sing higher" in key.text and "quarter tone" in key.text
    assert not [h for h in attempt_feedback(result(key=-20)) if h.kind == "key"]   # small: no hint


def test_spots_name_direction_note_and_song_time():
    times = np.arange(0, 4, 0.02)
    cents = np.where(times < 2, 0.0, 200.0)       # tonic, then the note a whole tone up
    worst = [Section(2.5, 3.0, mean_dev=-60.0, max_abs_dev=80.0, mean_abs_dev=60.0),
             Section(0.5, 1.0, mean_dev=40.0, max_abs_dev=50.0, mean_abs_dev=40.0),
             Section(1.2, 1.5, mean_dev=5.0, max_abs_dev=60.0, mean_abs_dev=40.0)]   # wobbly
    hints = attempt_feedback(result(pct=60, worst=worst, ref_times=times, ref_cents=cents),
                             name_tonic_hz=146.83, time_offset=10.0)
    spots = [h for h in hints if h.kind == "spot"]
    assert [h.start for h in spots] == [10.5, 11.2, 12.5]          # in song time, in order
    assert spots[0].direction == LOWER and "At 0:10 (Re)" in spots[0].text
    assert spots[1].direction == OK and "steadier" in spots[1].text
    assert spots[2].direction == HIGHER and "(Mi)" in spots[2].text and "sing higher" in spots[2].text
    assert spots[2].end == pytest.approx(13.0)


def test_spots_are_limited():
    worst = [Section(i, i + 0.5, -50.0, 60.0, 50.0) for i in range(5)]
    hints = attempt_feedback(result(pct=30, worst=worst), cfg={"max_spots": 2})
    assert len([h for h in hints if h.kind == "spot"]) == 2


def test_timing_hints():
    fast = [h.text for h in attempt_feedback(result(timing=0.6)) if h.kind == "timing"]
    slow = [h.text for h in attempt_feedback(result(timing=1.4)) if h.kind == "timing"]
    assert fast and "faster" in fast[0] and "hold the long notes longer" in fast[0]
    assert slow and "slower" in slow[0]
    assert not [h for h in attempt_feedback(result(timing=1.0)) if h.kind == "timing"]


def test_feedback_from_a_real_score_of_a_flat_attempt():
    t = np.arange(0, 3, 0.01)
    ref = np.where(t < 1.5, 0.0, 300.0)
    att = ref - 70.0                                # sung about a quarter tone too low throughout
    mk = lambda c: PitchCurve("x.wav", 44100, 0.01, 185.0, t, 185.0 * 2 ** (c / 1200), c,
                              np.ones_like(t, bool))
    hints = attempt_feedback(score_curves(mk(ref), mk(att), fold=False))
    assert any(h.kind == "key" and h.direction == HIGHER for h in hints)


def test_live_direction():
    teacher = [0.0, 5.0, 200.0, 205.0]              # around now the teacher sings two notes
    assert live_direction([198, 201, 203], teacher) == OK
    assert live_direction([140, 141, 139], teacher) == HIGHER     # nearest note is 200, I am below
    assert live_direction([60, 62, 61], teacher) == LOWER         # nearest is 5, I am above
    assert live_direction([np.nan, 100.0], teacher) is None        # too few voiced values
    assert live_direction([100, 100, 100], [np.nan]) is None       # teacher silent here


# ---------------------------------------------------------------- gentle level

from avaz.feedback import LiveHold, gentle_feedback, held_notes, note_hits, stars, stretch_onto


def steps(times, notes):
    """A curve that holds each ``(start, end, cents)`` note, silent in between."""
    out = np.full(times.size, np.nan)
    for a, b, c in notes:
        out[(times >= a) & (times < b)] = c
    return out


def test_held_notes_skip_ornaments_and_find_my_answer_nearby():
    t = np.arange(0, 3, 0.02)
    ref = steps(t, [(0.0, 0.6, 0.0), (1.0, 1.6, 200.0)])
    ornament = (t >= 0.6) & (t < 1.0)
    ref[ornament] = 300 + 150 * np.sin(np.arange(ornament.sum()) * 1.5)   # fast, never steady
    mine = steps(t, [(0.2, 0.5, 10.0), (1.5, 1.8, 120.0)])                # late on the second
    notes = held_notes(t, ref, mine)
    assert [(round(n.start, 2), round(n.teacher)) for n in notes] == [(0.0, 0), (1.0, 200)]
    assert notes[0].mine == pytest.approx(10.0)
    assert notes[1].mine == pytest.approx(120.0)      # found 0.2 s late, and it is wrong
    silent = held_notes(t, ref, np.full(t.size, np.nan))
    assert all(np.isnan(n.mine) for n in silent)


def test_a_slide_through_the_note_does_not_count():
    t = np.arange(0, 1, 0.02)
    ref = steps(t, [(0.0, 1.0, 0.0)])
    mine = np.linspace(-300, 300, t.size)             # glides straight through the teacher's note
    (note,) = held_notes(t, ref, mine)
    assert not note.steady and not note.hit(50)


def test_stretch_onto_evens_out_a_faster_attempt():
    t = np.arange(0, 2, 0.02)
    ref = steps(t, [(0.0, 1.0, 0.0), (1.0, 2.0, 200.0)])
    mine = steps(t, [(0.0, 0.8, 0.0), (0.8, 1.6, 200.0)])     # the same, 20 % faster
    on_ref = stretch_onto(t, ref, t, mine)
    assert np.nanmedian(on_ref[t < 0.9]) == pytest.approx(0.0)
    assert np.nanmedian(on_ref[t > 1.1]) == pytest.approx(200.0)


def scored(ref_notes, my_notes, dur=4.0):
    t = np.arange(0.01, dur, 0.02)
    ref, mine = steps(t, ref_notes), steps(t, my_notes)
    return ScoreResult(
        mad=10.0, median_abs=8.0, pct_within=50.0, tolerance=25.0, octave_shift=0.0,
        timing_ratio=1.0, n_pairs=100, worst=[], key_offset=0.0, ref_times=t, ref_cents=ref,
        att_on_ref=mine, dev_on_ref=mine - ref, att_times=t, att_cents=mine)


TEACHER = [(0.0, 0.5, 0.0), (0.7, 1.2, 200.0), (1.4, 1.9, 300.0), (2.1, 2.6, 500.0)]


def test_gentle_counts_long_notes_with_stars_and_no_tip_when_all_hit():
    hints = gentle_feedback(scored(TEACHER, [(a, b, c + 30) for a, b, c in TEACHER]))
    assert [h.kind for h in hints] == ["overall"]
    assert "You hit 4 of 4 long notes" in hints[0].text and stars(1.0) in hints[0].text


def test_gentle_one_overall_tip_and_no_marks_when_everything_is_a_bit_low():
    hints = gentle_feedback(scored(TEACHER, [(a, b, c - 70) for a, b, c in TEACHER]))
    tips = [h for h in hints if h.kind == "tip"]
    assert len(tips) == 1 and "aim a bit higher overall" in tips[0].text
    assert not [h for h in hints if h.kind == "mark"]


def test_gentle_marks_only_the_very_wrong_note():
    mine = [(a, b, c + (250 if c == 300 else 20)) for a, b, c in TEACHER]
    hints = gentle_feedback(scored(TEACHER, mine), name_tonic_hz=146.83, time_offset=60.0)
    marks = [h for h in hints if h.kind == "mark"]
    assert len(marks) == 1 and marks[0].start == pytest.approx(61.4, abs=0.02) and marks[0].text == ""
    tip = [h for h in hints if h.kind == "tip"][0]
    assert "the note at 1:01 (Fa)" in tip.text and "too high" in tip.text
    assert "3 of 4" in hints[0].text


def test_gentle_celebrates_progress_but_not_a_worse_try():
    good = scored(TEACHER, [(a, b, c) for a, b, c in TEACHER])
    assert note_hits(good) == (4, 4)
    better = gentle_feedback(good, previous=(2, 4))
    assert any(h.kind == "progress" and "2 of 4 before" in h.text for h in better)
    assert not any(h.kind == "progress" for h in gentle_feedback(good, previous=(4, 4)))
    bad = scored(TEACHER, [(a, b, c + 300) for a, b, c in TEACHER])
    assert not any(h.kind == "progress" for h in gentle_feedback(bad, previous=(4, 4)))


def test_live_hold_waits_before_showing_and_ignores_being_on_the_note():
    hold = LiveHold(0.5)
    assert hold.update(HIGHER, 0.0) is None
    assert hold.update(HIGHER, 0.4) is None
    assert hold.update(HIGHER, 0.6) == HIGHER
    assert hold.update(OK, 0.7) is None
    assert hold.update(LOWER, 0.8) is None            # a new direction starts the wait again
    assert hold.update(LOWER, 1.31) == LOWER
