import json

import numpy as np
import pytest

from avaz.cents import hz_to_cents
from avaz.live import PitchStream
from avaz.pitch_offline import PitchCurve, save_curve
from avaz.practice import (Session, IDLE, PLAY, RESPOND, DONE, octave_shift, time_stretch,
                           Attempt, Phrase, save_attempt, load_phrase, sibling_phrases)
from avaz.pitch_live import NumpyYin


def test_session_after_mode_walks_play_then_respond():
    s = Session(play_len=1000, respond_len=1500, mode="after")
    assert s.phase == IDLE and s.advance(100) == IDLE
    s.start()
    assert s.advance(600) == PLAY
    assert s.advance(600) == PLAY          # crosses the end of the phrase
    assert s.phase == RESPOND and s.pos == 0
    assert s.advance(1499) == RESPOND
    assert s.advance(1) == RESPOND
    assert s.phase == DONE
    assert s.advance(50) == DONE
    s.finish()
    assert s.phase == IDLE and s.attempts == 1


def test_session_along_mode_records_during_play():
    s = Session(play_len=1000, respond_len=0, mode="along")
    assert s.recording_phase == PLAY
    s.start()
    s.advance(1000)
    assert s.phase == DONE
    s.stop()
    assert s.phase == IDLE and s.attempts == 0


def test_octave_shift():
    teacher = np.full(50, 100.0)
    assert octave_shift(np.full(50, -1100.0), teacher) == 1200.0
    assert octave_shift(np.full(50, 2500.0), teacher) == -2400.0
    assert octave_shift(np.full(50, 300.0), teacher) == 0.0
    assert octave_shift(np.full(5, -1100.0), teacher) == 0.0     # too little data
    mixed = np.concatenate([np.full(50, -1100.0), np.full(10, np.nan)])
    assert octave_shift(mixed, teacher) == 1200.0


def test_time_stretch_changes_length_not_pitch():
    sr = 22050
    t = np.arange(2 * sr) / sr
    y = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    slow = time_stretch(y, sr, 0.5)
    assert slow.size == pytest.approx(2 * y.size, rel=0.02)
    assert time_stretch(y, sr, 1.0) is y
    yin = NumpyYin(sample_rate=sr, frame_length=2048, fmin=70, fmax=1000)
    mid = slow.size // 2
    f0 = yin.detect(slow[mid:mid + 2048])
    assert abs(hz_to_cents(f0, 220.0)) < 10


def test_attempt_collects_audio_and_curve(tmp_path):
    sr = 44100
    stream = PitchStream(NumpyYin(sample_rate=sr, frame_length=2048), tonic_hz=185.0,
                         hop_length=256, smoothing_frames=1)
    att = Attempt(stream)
    t = np.arange(sr) / sr
    y = (0.3 * np.sin(2 * np.pi * 185.0 * t)).astype(np.float32)
    for i in range(0, y.size, 512):
        att.add(y[i:i + 512])
    assert att.audio.size == y.size
    curve = att.curve("x.wav")
    assert curve.tonic_hz == 185.0
    assert np.nanmedian(curve.cents) == pytest.approx(0.0, abs=5)

    phrase = Phrase(tmp_path / "song" / "p1.wav", y, sr, None)
    wav = save_attempt(att, phrase, mode="after", speed=0.8, teacher_tonic=185.0, shift=0.0,
                       out_dir=tmp_path / "attempts")
    assert wav.exists() and wav.with_suffix(".pitch.json").exists()
    meta = json.loads(wav.with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert meta["mode"] == "after" and meta["speed"] == 0.8


def test_load_phrase_and_siblings(tmp_path):
    import soundfile as sf
    sr = 22050
    folder = tmp_path / "song"
    folder.mkdir()
    for name in ["b.wav", "a.wav", "call_response.wav"]:
        sf.write(str(folder / name), np.zeros(sr), sr)
    times = np.arange(0, 1.0, 0.01)
    f0 = np.full(times.size, 200.0)
    save_curve(PitchCurve("a.wav", sr, 0.01, 200.0, times, f0, hz_to_cents(f0, 200.0),
                          np.isfinite(f0)), folder / "a.pitch.json")
    ph = load_phrase(folder / "a.pitch.json", sample_rate=sr)
    assert ph.audio_path.name == "a.wav" and ph.curve is not None
    assert ph.duration == pytest.approx(1.0)
    assert [p.name for p in sibling_phrases(ph.audio_path)] == ["a.wav", "b.wav"]


def test_attempt_time_offset_shifts_points():
    sr = 44100
    stream = PitchStream(NumpyYin(sample_rate=sr, frame_length=2048), tonic_hz=185.0,
                         hop_length=256, smoothing_frames=1)
    att = Attempt(stream, time_offset=0.1)
    t = np.arange(sr // 2) / sr
    y = (0.3 * np.sin(2 * np.pi * 185.0 * t)).astype(np.float32)
    att.add(y)
    first = att.points[0][0]
    assert first == pytest.approx(2048 / 2 / sr - 0.1, abs=256 / sr)


def test_session_waits_for_trigger_then_responds():
    from avaz.practice import WAIT
    s = Session(play_len=1000, respond_len=1500, mode="after", wait_len=5000)
    s.start()
    s.advance(1000)
    assert s.phase == WAIT and s.pos == 0
    assert s.advance(300) == WAIT
    assert s.trigger(preroll=200)
    assert s.phase == RESPOND and s.pos == 200
    assert not s.trigger(0)                     # only valid while waiting
    s.advance(1300)
    assert s.phase == DONE and not s.timed_out


def test_session_wait_times_out():
    from avaz.practice import WAIT
    s = Session(play_len=100, respond_len=100, mode="after", wait_len=500)
    s.start()
    s.advance(100)
    assert s.phase == WAIT
    s.advance(500)
    assert s.phase == DONE and s.timed_out


def test_onset_detector_ignores_silence_and_noise_then_fires_on_voice():
    from avaz.practice import OnsetDetector
    sr = 44100
    det = NumpyYin(sample_rate=sr, frame_length=2048)
    onset = OnsetDetector(det, hop_length=256, rms_db=-40, voiced_frames=6, preroll_seconds=0.1)
    rng = np.random.default_rng(0)
    silence = np.zeros(sr // 2, dtype=np.float32)
    noise = (0.05 * rng.normal(size=sr // 4)).astype(np.float32)
    t = np.arange(sr // 2) / sr
    voice = (0.3 * np.sin(2 * np.pi * 180 * t)).astype(np.float32)
    fired_at = None
    stream = np.concatenate([silence, noise, voice])
    for i in range(0, stream.size, 256):
        if onset.feed(stream[i:i + 256]):
            fired_at = i
            break
    assert fired_at is not None
    voice_start = silence.size + noise.size
    assert voice_start <= fired_at <= voice_start + 0.1 * sr
    assert 0 < onset.preroll.size <= int(0.1 * sr) + 256
    assert onset.feed(voice[:256]) is False      # fires only once
