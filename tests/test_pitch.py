import numpy as np
import pytest

from avaz.cents import hz_to_cents
from avaz.pitch_live import NumpyYin
from avaz.pitch_offline import (PitchCurve, remove_short_islands, remove_outliers,
                                save_curve, load_curve)


SR = 44100
N = 2048


def tone(freq, n=N, sr=SR, amp=0.3, harmonics=(1.0, 0.5, 0.25)):
    t = np.arange(n) / sr
    y = sum(a * np.sin(2 * np.pi * freq * (k + 1) * t) for k, a in enumerate(harmonics))
    return amp * y / max(abs(y).max(), 1e-9)


@pytest.mark.parametrize("freq", [80.0, 110.0, 196.0, 261.6, 440.0, 880.0])
def test_numpy_yin_on_harmonic_tone(freq):
    yin = NumpyYin(sample_rate=SR, frame_length=N, fmin=70, fmax=1000)
    f0 = yin.detect(tone(freq))
    assert np.isfinite(f0)
    assert abs(hz_to_cents(f0, freq)) < 5


def test_numpy_yin_silence_and_noise_are_unvoiced():
    yin = NumpyYin(sample_rate=SR, frame_length=N)
    assert np.isnan(yin.detect(np.zeros(N)))
    rng = np.random.default_rng(0)
    assert np.isnan(yin.detect(0.1 * rng.normal(size=N)))


def test_numpy_yin_rejects_wrong_frame_length():
    yin = NumpyYin(sample_rate=SR, frame_length=N)
    with pytest.raises(ValueError):
        yin.detect(np.zeros(N + 1))


def test_remove_short_islands():
    f0 = np.array([np.nan, 100, np.nan, 100, 100, 100, np.nan, 100, 100])
    out = remove_short_islands(f0, min_frames=3)
    assert np.isnan(out[1])
    assert np.isfinite(out[3:6]).all()
    assert np.isnan(out[7:]).all()


def test_curve_round_trip(tmp_path):
    times = np.arange(5) * 0.01
    f0 = np.array([196.0, np.nan, 200.0, 210.0, np.nan])
    curve = PitchCurve(source="x.wav", sample_rate=44100, hop_seconds=0.01, tonic_hz=196.0,
                       times=times, f0_hz=f0, cents=hz_to_cents(f0, 196.0),
                       voiced=np.isfinite(f0))
    path = save_curve(curve, tmp_path / "x.pitch.json")
    back = load_curve(path)
    assert back.source == "x.wav" and back.tonic_hz == 196.0
    assert np.allclose(back.times, times)
    assert np.isnan(back.f0_hz[1]) and np.isnan(back.cents[4])
    assert back.f0_hz[0] == pytest.approx(196.0)
    assert list(back.voiced) == [True, False, True, True, False]


def test_with_tonic_recomputes_cents():
    f0 = np.array([196.0, 392.0])
    curve = PitchCurve("x", 44100, 0.01, 196.0, np.arange(2) * 0.01, f0,
                       hz_to_cents(f0, 196.0), np.isfinite(f0))
    moved = curve.with_tonic(392.0)
    assert moved.cents[0] == pytest.approx(-1200.0)
    assert moved.cents[1] == pytest.approx(0.0)


def test_remove_outliers_blanks_far_frames_only():
    f0 = np.array([200.0, 210.0, np.nan, 190.0, 1600.0, 40.0, 205.0])
    out = remove_outliers(f0, max_cents_from_median=1500)
    assert np.isnan(out[4]) and np.isnan(out[5])
    assert np.isfinite(out[[0, 1, 3, 6]]).all()
    assert np.isnan(out[2])
    # disabled
    assert np.array_equal(remove_outliers(f0, 0), f0, equal_nan=True)


def test_remove_boundary_pins():
    from avaz.pitch_offline import remove_boundary_pins
    fmin, fmax = 70.0, 1000.0
    f0 = np.array([70.0, 70.5, 90.0, 500.0, 998.0, 1000.0, np.nan])
    out = remove_boundary_pins(f0, fmin, fmax, guard_cents=25)
    assert np.isnan(out[0]) and np.isnan(out[1])   # right at / just above fmin
    assert np.isfinite(out[2]) and np.isfinite(out[3])
    assert np.isnan(out[4]) and np.isnan(out[5])   # right at / just below fmax
    assert np.isnan(out[6])
    assert np.array_equal(remove_boundary_pins(f0, fmin, fmax, 0), f0, equal_nan=True)
