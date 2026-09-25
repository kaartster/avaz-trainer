import numpy as np
import pytest

from avaz.cents import (hz_to_cents, cents_to_hz, fold_octave, fold_to_reference,
                        pitch_histogram, estimate_tonic)


def test_hz_to_cents_basic():
    assert hz_to_cents(220.0, 220.0) == pytest.approx(0.0)
    assert hz_to_cents(440.0, 220.0) == pytest.approx(1200.0)
    assert hz_to_cents(110.0, 220.0) == pytest.approx(-1200.0)
    # one equal tempered semitone
    assert hz_to_cents(220.0 * 2 ** (1 / 12), 220.0) == pytest.approx(100.0)


def test_hz_to_cents_nan_and_zero():
    out = hz_to_cents(np.array([220.0, np.nan, 0.0, -5.0]), 220.0)
    assert out[0] == pytest.approx(0.0)
    assert np.isnan(out[1:]).all()
    assert np.isnan(hz_to_cents(float("nan"), 220.0))


def test_round_trip():
    hz = np.array([70.0, 196.0, 555.5, 1000.0])
    assert np.allclose(cents_to_hz(hz_to_cents(hz, 196.0), 196.0), hz)


def test_fold_octave():
    assert fold_octave(1350.0) == pytest.approx(150.0)
    assert fold_octave(-100.0) == pytest.approx(1100.0)
    assert fold_octave(1200.0) == pytest.approx(0.0)
    assert np.isnan(fold_octave(float("nan")))


def test_fold_to_reference():
    # sung an octave below the reference: move up
    assert fold_to_reference(-1150.0, 0.0) == pytest.approx(50.0)
    # already within half an octave: unchanged
    assert fold_to_reference(500.0, 0.0) == pytest.approx(500.0)
    # arrays, elementwise
    out = fold_to_reference(np.array([-1200.0, 2400.0, np.nan]), np.array([0.0, 0.0, 0.0]))
    assert out[0] == pytest.approx(0.0)
    assert out[1] == pytest.approx(0.0)
    assert np.isnan(out[2])


def test_pitch_histogram_folds_octaves():
    cents = np.array([0.0, 1200.0, 2400.0, 150.0, -1050.0, np.nan])
    centers, counts = pitch_histogram(cents, bin_cents=10.0, fold=True, smooth_bins=1)
    assert centers.size == 120
    assert counts.sum() == 5
    assert counts[0] == 3          # 0, 1200, 2400 all fold to bin 0
    assert counts[15] == 2         # 150 and -1050 fold to 150


def test_estimate_tonic_histogram_picks_most_common_note():
    tonic = 185.0
    rng = np.random.default_rng(0)
    # 60% on the tonic, the rest spread on other notes, some an octave up, some NaN
    f0 = np.concatenate([
        tonic * 2 ** (rng.normal(0, 8, 600) / 1200),
        tonic * 2 ** ((300 + rng.normal(0, 8, 200)) / 1200),
        tonic * 2 ** ((1200 + rng.normal(0, 8, 100)) / 1200),
        tonic * 2 ** ((700 + rng.normal(0, 8, 100)) / 1200),
        np.full(50, np.nan),
    ])
    est = estimate_tonic(f0, method="histogram")
    assert abs(hz_to_cents(est, tonic)) < 10


def test_estimate_tonic_final():
    f0 = np.concatenate([np.full(100, 300.0), np.full(20, np.nan), np.full(50, 200.0)])
    est = estimate_tonic(f0, method="final", hop_seconds=0.01, final_seconds=0.3)
    assert est == pytest.approx(200.0)


def test_estimate_tonic_no_voiced():
    with pytest.raises(ValueError):
        estimate_tonic(np.full(10, np.nan))
