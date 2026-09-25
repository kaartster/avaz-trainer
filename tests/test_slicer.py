import numpy as np
import pytest

from avaz.cents import hz_to_cents
from avaz.pitch_offline import PitchCurve
from avaz.slicer import (Phrase, detect_phrases, write_labels, read_labels, slice_curve,
                         build_call_response, export_phrases, safe_filename)

SR = 22050


def bursts(spec, sr=SR, freq=200.0):
    """spec: list of (seconds, loud) tuples -> signal of tones and silences."""
    parts = []
    for seconds, loud in spec:
        n = int(seconds * sr)
        t = np.arange(n) / sr
        parts.append((0.3 * np.sin(2 * np.pi * freq * t)) if loud else np.zeros(n))
    return np.concatenate(parts).astype(np.float32)


def test_detect_phrases_basic():
    y = bursts([(0.5, False), (2.0, True), (1.0, False), (1.5, True), (0.5, False)])
    phrases = detect_phrases(y, SR, silence_db=-40, min_pause_seconds=0.5,
                             min_phrase_seconds=0.8, pad_seconds=0.0)
    assert len(phrases) == 2
    assert phrases[0].start == pytest.approx(0.5, abs=0.1)
    assert phrases[0].end == pytest.approx(2.5, abs=0.1)
    assert phrases[1].start == pytest.approx(3.5, abs=0.1)
    assert phrases[1].end == pytest.approx(5.0, abs=0.1)
    assert phrases[0].label == "phrase_01" and phrases[1].label == "phrase_02"


def test_short_pause_does_not_split():
    y = bursts([(1.5, True), (0.2, False), (1.5, True)])
    phrases = detect_phrases(y, SR, silence_db=-40, min_pause_seconds=0.5, pad_seconds=0.0)
    assert len(phrases) == 1
    assert phrases[0].duration == pytest.approx(3.2, abs=0.1)


def test_short_phrase_is_dropped():
    y = bursts([(1.0, False), (0.3, True), (1.0, False), (2.0, True)])
    phrases = detect_phrases(y, SR, silence_db=-40, min_pause_seconds=0.5,
                             min_phrase_seconds=0.8, pad_seconds=0.0)
    assert len(phrases) == 1
    assert phrases[0].start == pytest.approx(2.3, abs=0.1)


def test_padding_is_clamped():
    y = bursts([(0.05, False), (1.0, True), (0.6, False), (1.0, True)])
    phrases = detect_phrases(y, SR, silence_db=-40, min_pause_seconds=0.5,
                             min_phrase_seconds=0.5, pad_seconds=1.0)
    assert len(phrases) == 2
    assert phrases[0].start == 0.0
    assert phrases[0].end <= phrases[1].start
    assert phrases[1].end == pytest.approx(y.size / SR)


def test_labels_round_trip(tmp_path):
    phrases = [Phrase(0.5, 2.0, "a"), Phrase(3.0, 4.25, "b")]
    path = write_labels(phrases, tmp_path / "labels.txt")
    text = path.read_text(encoding="utf-8")
    assert text.splitlines()[0].split("\t")[2] == "a"
    back = read_labels(path)
    assert [(p.start, p.end, p.label) for p in back] == [(0.5, 2.0, "a"), (3.0, 4.25, "b")]


def test_read_labels_sorts_and_names_unlabeled(tmp_path):
    p = tmp_path / "l.txt"
    p.write_text("3.0\t4.0\n1.0\t2.0\tfirst\n5.0\t5.0\tpoint\n", encoding="utf-8")
    back = read_labels(p)
    assert [b.label for b in back] == ["first", "phrase_02"]


def test_slice_curve_rebases_time():
    times = np.arange(10) * 0.1
    f0 = np.full(10, 200.0)
    curve = PitchCurve("x", SR, 0.1, 200.0, times, f0, hz_to_cents(f0, 200.0), np.isfinite(f0))
    part = slice_curve(curve, 0.3, 0.6)
    assert part.times.size == 3
    assert part.times[0] == pytest.approx(0.0)
    assert part.tonic_hz == 200.0


def test_call_response_lengths():
    y = bursts([(1.0, True), (0.5, False), (2.0, True)])
    phrases = [Phrase(0.0, 1.0, "p1"), Phrase(1.5, 3.5, "p2")]
    track, labels = build_call_response(y, SR, phrases, margin_seconds=0.5)
    expected = (1.0 + 1.0 + 0.5) + (2.0 + 2.0 + 0.5)
    assert track.size == pytest.approx(expected * SR, abs=2)
    assert [l.label for l in labels] == ["p1", "p1_you", "p2", "p2_you"]
    assert labels[1].duration == pytest.approx(1.5, abs=1e-3)
    assert labels[3].start == pytest.approx(2.5 + 2.0, abs=1e-3)
    # the response gap is silent
    a, b = int(labels[1].start * SR) + 10, int(labels[1].end * SR) - 10
    assert np.abs(track[a:b]).max() == 0


def test_export_phrases_writes_wav_and_curve(tmp_path):
    y = bursts([(1.0, True)])
    times = np.arange(0, 1.0, 0.01)
    f0 = np.full(times.size, 200.0)
    curve = PitchCurve("x", SR, 0.01, 200.0, times, f0, hz_to_cents(f0, 200.0),
                       np.isfinite(f0))
    written = export_phrases(y, SR, [Phrase(0.2, 0.7, "p1")], tmp_path, curve=curve)
    assert written == [tmp_path / "p1.wav"]
    assert (tmp_path / "p1.pitch.json").exists()
    import soundfile as sf
    data, sr = sf.read(str(written[0]))
    assert sr == SR and data.size == pytest.approx(0.5 * SR, abs=1)


def test_safe_filename():
    assert safe_filename("intro: part 1/2?") == "intro_ part 1_2_"
    assert safe_filename("  .. ") == "phrase"
    assert safe_filename("با من صنما") == "با من صنما"
