import numpy as np
import pytest

from avaz.cents import pitch_histogram
from avaz.scales import (Scale, load_scales, nearest_note, find_histogram_peaks,
                         suggest_scale_positions)


def test_load_default_scales():
    scales = load_scales()
    assert "shur" in scales and "mahur" in scales
    assert scales["shur"].positions[0] == 0
    assert scales["shur"].positions[-1] == 1200
    assert len(scales["shur"].labels) == len(scales["shur"].positions)


def test_scale_label_mismatch_raises():
    with pytest.raises(ValueError):
        Scale("bad", [0, 100], ["only one"])


def test_nearest_note_within_octave():
    shur = Scale("shur", [0, 150, 300, 500, 700, 800, 1000, 1200])
    pos, label, dev = nearest_note(160.0, shur)
    assert pos == 150 and dev == pytest.approx(10.0)
    pos, label, dev = nearest_note(-20.0, shur)
    assert pos == 0 and dev == pytest.approx(-20.0)


def test_nearest_note_other_octaves():
    shur = Scale("shur", [0, 150, 300, 500, 700, 800, 1000, 1200])
    pos, _, dev = nearest_note(1350.0, shur)
    assert pos == 1350 and dev == pytest.approx(0.0)
    pos, _, dev = nearest_note(-1210.0, shur)
    assert pos == -1200 and dev == pytest.approx(-10.0)
    pos, _, dev = nearest_note(1190.0, shur)
    assert pos == 1200 and dev == pytest.approx(-10.0)


def test_nearest_note_nan():
    shur = Scale("shur", [0, 150, 300])
    pos, label, dev = nearest_note(float("nan"), shur)
    assert np.isnan(pos) and np.isnan(dev) and label == ""


def test_positions_in_range_repeats_octaves():
    s = Scale("s", [0, 500, 1200], ["t", "4", "o"])
    got = s.positions_in_range(-600, 1300)
    assert [c for c, _ in got] == [0, 500, 1200]
    assert [l for _, l in got] == ["t", "4", "t"]
    got = s.positions_in_range(-800, 0)
    assert [c for c, _ in got] == [-700, 0]


def test_suggest_positions_from_synthetic_histogram():
    rng = np.random.default_rng(1)
    true_positions = [0, 140, 300, 500, 700, 790, 1000]
    cents = np.concatenate([p + rng.normal(0, 10, 300) for p in true_positions])
    # add a tiny bit of noise everywhere
    cents = np.concatenate([cents, rng.uniform(0, 1200, 100)])
    centers, counts = pitch_histogram(cents, bin_cents=10.0, fold=True, smooth_bins=3)
    peaks = find_histogram_peaks(centers, counts)
    assert len(peaks) == len(true_positions)
    suggested = suggest_scale_positions(centers, counts)
    assert suggested[0] == 0 and suggested[-1] == 1200
    assert len(suggested) == len(true_positions) + 1
    for want, got in zip(true_positions, suggested):
        assert abs(want - got) <= 15


def test_suggest_positions_snaps_tonic_near_1200():
    rng = np.random.default_rng(2)
    cents = np.concatenate([1190 + rng.normal(0, 5, 300), 500 + rng.normal(0, 5, 200)])
    centers, counts = pitch_histogram(cents, bin_cents=10.0, fold=True, smooth_bins=3)
    suggested = suggest_scale_positions(centers, counts)
    assert suggested == [0.0, 500.0, 1200.0] or suggested[0] == 0.0
