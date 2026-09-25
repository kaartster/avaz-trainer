import json

import numpy as np
import pytest

from avaz.cents import hz_to_cents
from avaz.compare import (resample_to_bins, dtw_align, worst_sections, score_curves,
                          record_score, load_history, history_rows, history_path)
from avaz.pitch_offline import PitchCurve


def make_curve(times, cents, tonic=185.0):
    cents = np.asarray(cents, dtype=float)
    f0 = np.where(np.isfinite(cents), tonic * 2 ** (cents / 1200), np.nan)
    return PitchCurve("x.wav", 44100, float(times[1] - times[0]), tonic, np.asarray(times),
                      f0, cents, np.isfinite(cents))


def melody(seconds=4.0, hop=0.005):
    """A little tune with a pause: 0, 200, 300, pause, 500, 300 cents, with vibrato."""
    t = np.arange(0, seconds, hop)
    c = np.full(t.size, np.nan)
    notes = [(0.0, 0.8, 0), (0.8, 1.6, 200), (1.6, 2.2, 300), (2.6, 3.3, 500), (3.3, 4.0, 300)]
    for a, b, n in notes:
        m = (t >= a) & (t < b)
        c[m] = n + 15 * np.sin(2 * np.pi * 6 * t[m])
    return t, c


def test_resample_to_bins_median_and_gaps():
    t = np.arange(0, 0.1, 0.005)
    c = np.full(t.size, 100.0)
    c[10:] = np.nan
    ct, cb = resample_to_bins(t, c, bin_seconds=0.02)
    assert cb.size == 5
    assert cb[0] == 100.0 and cb[1] == 100.0 and cb[2] == 100.0
    assert np.isnan(cb[3]) and np.isnan(cb[4])
    assert ct[0] == pytest.approx(0.01)


def test_dtw_identical_is_diagonal():
    a = np.array([0.0, 10.0, 20.0, 30.0, 40.0])
    path = dtw_align(a, a)
    assert path.tolist() == [[i, i] for i in range(5)]


def test_dtw_handles_time_stretch():
    a = np.array([0.0, 0.0, 100.0, 100.0, 200.0, 200.0])
    b = np.array([0.0, 100.0, 200.0])
    path = dtw_align(a, b, band=1.0)
    pairs = {tuple(p) for p in path.tolist()}
    assert (0, 0) in pairs and (5, 2) in pairs
    dev = [abs(a[i] - b[j]) for i, j in path]
    assert max(dev) == 0


def test_worst_sections_merges_and_ranks():
    times = np.arange(0, 3.0, 0.02) + 0.01
    dev = np.zeros(times.size)
    dev[(times > 0.5) & (times < 1.0)] = 40          # 0.5 s flat... sharp by 40
    dev[(times > 1.05) & (times < 1.3)] = 45         # gap of 0.05 s -> merged with the above
    dev[(times > 2.0) & (times < 2.1)] = 80          # 0.1 s: too short
    dev[(times > 2.5) & (times < 2.9)] = -60
    secs = worst_sections(times, dev, tolerance=25)
    assert len(secs) == 2
    assert secs[0].start == pytest.approx(0.5, abs=0.03) and secs[0].end == pytest.approx(1.3, abs=0.03)
    assert secs[0].mean_dev > 0
    assert secs[1].mean_dev == pytest.approx(-60)
    assert "flat" in secs[1].describe()


def test_score_identical_curves_is_perfect():
    t, c = melody()
    r = score_curves(make_curve(t, c), make_curve(t, c))
    assert r.mad == pytest.approx(0.0, abs=1e-6)
    assert r.pct_within == 100.0
    assert r.worst == []
    assert r.timing_ratio == pytest.approx(1.0)


def test_score_constant_offset():
    t, c = melody()
    r = score_curves(make_curve(t, c), make_curve(t, c + 40), tolerance=25)
    assert r.mad == pytest.approx(40, abs=2)
    assert r.pct_within < 10            # DTW may pair a few vibrato peaks with troughs
    assert r.median_offset == pytest.approx(40, abs=2)
    assert "sharp by 40" in r.summary()
    assert r.worst and r.worst[0].mean_dev == pytest.approx(40, abs=5)


def test_score_octave_below_is_folded():
    t, c = melody()
    r = score_curves(make_curve(t, c), make_curve(t, c - 1200))
    assert r.octave_shift == 1200
    assert r.mad < 1


def test_score_slower_attempt_still_matches():
    t, c = melody()
    slow_t = t * 1.3                                  # same tune, 30% slower
    r = score_curves(make_curve(t, c), make_curve(slow_t, c), band=0.3)
    assert r.timing_ratio == pytest.approx(1.3, abs=0.05)
    assert r.mad < 8
    assert r.pct_within > 95


def test_score_finds_the_bad_note():
    t, c = melody()
    bad = c.copy()
    bad[(t >= 1.6) & (t < 2.2)] += 70                 # third note sung sharp
    r = score_curves(make_curve(t, c), make_curve(t, bad), tolerance=25)
    assert r.worst
    w = r.worst[0]
    assert w.start == pytest.approx(1.6, abs=0.05) and w.end == pytest.approx(2.2, abs=0.05)
    assert w.mean_dev == pytest.approx(70, abs=5)
    assert r.pct_within == pytest.approx(100 * (1 - 0.6 / 3.4), abs=3)


def test_score_better_singing_scores_higher():
    t, c = melody()
    rng = np.random.default_rng(0)
    good = c + rng.normal(0, 8, c.size)
    poor = c + rng.normal(0, 40, c.size)
    ref = make_curve(t, c)
    r_good, r_poor = score_curves(ref, make_curve(t, good)), score_curves(ref, make_curve(t, poor))
    assert r_good.pct_within > r_poor.pct_within
    assert r_good.mad < r_poor.mad


def test_history_record_and_rows(tmp_path):
    t, c = melody()
    r = score_curves(make_curve(t, c), make_curve(t, c + 10))
    wav = tmp_path / "20260101_120000.wav"
    wav.write_bytes(b"")
    (tmp_path / "20260101_120000.meta.json").write_text(
        json.dumps({"mode": "after", "speed": 0.8, "recorded_at": "20260101_120000"}), encoding="utf-8")
    path = record_score(wav, r, method="live")
    assert path == history_path(wav)
    hist = load_history(path)
    assert "20260101_120000" in hist
    assert hist["20260101_120000"]["speed"] == 0.8
    record_score(wav, r, method="offline")             # rescoring replaces, no duplicate
    assert len(load_history(path)) == 1
    rows = history_rows(load_history(path))
    assert rows[0]["method"] == "offline" and rows[0]["name"] == "20260101_120000"


def test_worst_sections_drops_alternating_runs():
    times = np.arange(0, 2.0, 0.02) + 0.01
    dev = np.zeros(times.size)
    # a vibrato phase mismatch: +30 / -30 alternating bins, mean about 0 but bins over tolerance
    alt = np.where(np.arange(times.size) % 2 == 0, 30.0, -30.0)
    dev[(times > 0.5) & (times < 1.5)] = alt[(times > 0.5) & (times < 1.5)]
    secs = worst_sections(times, dev, tolerance=25)
    assert len(secs) == 1 and "unsteady" in secs[0].describe()
    dev[(times > 0.5) & (times < 1.5)] = alt[(times > 0.5) & (times < 1.5)] * 0.8   # 24 cents: fine
    assert worst_sections(times, dev, tolerance=25) == []


def test_score_no_voiced_frames_does_not_crash():
    t, c = melody()
    silent = make_curve(t, np.full(t.size, np.nan))
    r = score_curves(make_curve(t, c), silent)
    assert np.isnan(r.mad) and r.pct_within == 0.0 and r.n_pairs == 0
    assert np.isnan(r.median_offset)
    assert isinstance(r.ref_times, np.ndarray) and r.ref_times.shape == r.ref_cents.shape
    r.summary()                          # must not raise
    r.to_record()                        # must not raise


def test_score_attempt_same_key_compares_absolute_pitch():
    from avaz.compare import score_attempt
    t, c = melody()
    teacher = make_curve(t, c, tonic=132.0)
    # I sing the exact same notes (same Hz) but my curve was measured from another tonic
    same_notes = make_curve(t, c + 1200 * np.log2(132.0 / 146.8), tonic=146.8)
    assert score_attempt(teacher, same_notes, same_key=True).mad < 1
    # a major third low in absolute pitch: same key must NOT forgive it
    low = make_curve(t, c - 400, tonic=132.0)
    r = score_attempt(teacher, low, same_key=True)
    assert r.octave_shift == 0 and r.pct_within == 0
    assert r.median_offset == pytest.approx(-400, abs=5)
    # a full octave low: same key must not fold it either
    octave_low = make_curve(t, c - 1200, tonic=132.0)
    r = score_attempt(teacher, octave_low, same_key=True)
    assert r.octave_shift == 0 and r.pct_within == 0
    assert r.median_offset == pytest.approx(-1200, abs=5)
    # outside same key, the octave is folded away as before
    assert score_attempt(teacher, octave_low, same_key=False).mad < 1
