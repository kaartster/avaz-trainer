import numpy as np
import pytest

from avaz.cents import hz_to_cents
from avaz.live import RingBuffer, PitchStream, LiveTrace, BlockQueue
from avaz.pitch_live import NumpyYin

SR = 44100
FRAME = 2048
HOP = 256


def sine(freq, seconds, sr=SR, amp=0.3):
    t = np.arange(int(seconds * sr)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_ring_buffer_keeps_latest():
    rb = RingBuffer(8)
    rb.push(np.arange(5))
    assert not rb.full
    rb.push(np.arange(5, 10))
    assert rb.full
    assert list(rb.latest()) == [2, 3, 4, 5, 6, 7, 8, 9]
    rb.push(np.arange(100, 120))
    assert list(rb.latest()) == list(range(112, 120))


def test_pitch_stream_tracks_a_tone_in_small_blocks():
    det = NumpyYin(sample_rate=SR, frame_length=FRAME)
    ps = PitchStream(det, tonic_hz=185.0, hop_length=HOP, smoothing_frames=1)
    y = sine(220.0, 0.5)
    points = []
    for i in range(0, y.size, 100):          # sound card blocks need not match the hop
        points.extend(ps.process(y[i:i + 100]))
    # first point appears once a full frame has arrived
    assert len(points) == (y.size // HOP) - (FRAME // HOP) + 1
    times = [p[0] for p in points]
    assert times == sorted(times)
    assert times[0] == pytest.approx(FRAME / 2 / SR, abs=HOP / SR)
    f0 = np.array([p[1] for p in points])
    assert np.isfinite(f0).all()
    assert np.abs(hz_to_cents(f0, 220.0)).max() < 5
    assert points[-1][2] == pytest.approx(hz_to_cents(220.0, 185.0), abs=5)


def test_pitch_stream_silence_gives_nan():
    det = NumpyYin(sample_rate=SR, frame_length=FRAME)
    ps = PitchStream(det, tonic_hz=185.0, hop_length=HOP)
    points = ps.process(np.zeros(FRAME + HOP * 4, dtype=np.float32))
    assert points and all(np.isnan(p[1]) for p in points)


def test_median_smoothing_removes_single_slip():
    class Fake:
        sample_rate = SR
        frame_length = FRAME
        def __init__(self):
            self.values = iter([200.0, 200.0, 400.0, 200.0, 200.0, np.nan, np.nan, np.nan])
        def detect(self, frame):
            return next(self.values)
    ps = PitchStream(Fake(), tonic_hz=200.0, hop_length=HOP, smoothing_frames=3)
    out = []
    ps.process(np.zeros(FRAME - HOP))         # fill the ring buffer except one hop
    for _ in range(8):
        out.extend(ps.process(np.zeros(HOP)))
    f0 = [p[1] for p in out]
    assert f0[2] == 200.0                     # the 400 Hz slip is voted out
    assert f0[3] == 200.0
    assert np.isnan(f0[-1])                   # three NaNs in a row -> NaN


def test_live_trace_window_and_readout():
    tr = LiveTrace(history_seconds=1.0, hop_seconds=0.1)
    pts = [(i * 0.1, 200.0, 100.0 + i) for i in range(25)]
    tr.append(pts)
    t, c = tr.window()
    assert t[0] >= tr.latest_time - 1.0
    assert t[-1] == pytest.approx(2.4)
    assert tr.latest_cents == pytest.approx(124.0)
    assert tr.stable_cents(0.3) == pytest.approx(np.median([122, 123, 124]), abs=1e-6)
    tr.append([(2.5, np.nan, np.nan)])
    assert np.isnan(tr.latest_cents)
    assert np.isfinite(tr.stable_cents(0.3))


def test_block_queue_drain():
    q = BlockQueue()
    assert q.drain() == []
    q.put(np.ones(3))
    q.put(np.zeros(2))
    blocks = q.drain()
    assert len(blocks) == 2 and blocks[0].size == 3
    assert q.drain() == []


def test_build_pitch_stream_uses_the_configured_silence_gate():
    from avaz.live import build_pitch_stream
    settings = {"audio": {"sample_rate": SR, "frame_length": FRAME, "hop_length": HOP,
                          "pitch_silence_db": -55}}
    ps = build_pitch_stream(settings, 132.0, backend="numpy", smoothing_frames=1)
    # soft singing at about -48 dBFS RMS: below the old -46 gate, above the new -55 one
    y = sine(150.0, 0.2, amp=0.0056)
    assert 20 * np.log10(np.sqrt(np.mean(y ** 2))) == pytest.approx(-48, abs=0.5)
    f0 = [p[1] for p in ps.process(y)]
    assert f0 and np.isfinite(f0).all()
    old = build_pitch_stream({"audio": {"sample_rate": SR, "frame_length": FRAME,
                                        "hop_length": HOP}}, 132.0, backend="numpy",
                             smoothing_frames=1)
    assert all(np.isnan(p[1]) for p in old.process(y))
