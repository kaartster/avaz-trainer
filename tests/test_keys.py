import pytest

from avaz.keys import hz_to_note, key_choices, note_label, note_to_hz


def test_note_to_hz_reference_points():
    assert note_to_hz(9, 4) == pytest.approx(440.0)          # La (A4)
    assert note_to_hz(2, 3) == pytest.approx(146.83, abs=0.01)   # Re (D3), Amir's key
    assert note_to_hz(6, 3) == pytest.approx(185.0, abs=0.01)    # Fa diez (F#3)


def test_hz_to_note_round_trip_and_offset():
    assert hz_to_note(note_to_hz(4, 3)) == (4, 3, pytest.approx(0.0, abs=1e-6))
    index, octave, off = hz_to_note(167.0)                   # the teacher's Mi
    assert (index, octave) == (4, 3) and off == pytest.approx(22.6, abs=0.5)
    assert hz_to_note(note_to_hz(11, 2) * 2 ** (49 / 1200))[:2] == (11, 2)
    assert hz_to_note(note_to_hz(11, 2) * 2 ** (51 / 1200))[:2] == (0, 3)   # rounds up to Do


def test_note_label():
    assert note_label(167.0) == "Mi (E3) +23"
    assert note_label(146.83) == "Re (D3)"
    assert note_label(167.0, show_cents=False) == "Mi (E3)"


def test_key_choices_cover_the_octaves_in_order():
    choices = key_choices(2, 4)
    assert len(choices) == 36
    assert choices[0][0] == "Do (C2)" and choices[-1][0] == "Si (B4)"
    hz = [h for _, h in choices]
    assert hz == sorted(hz)


@pytest.mark.parametrize("name, index", [
    ("با من صنما_ دشتی_ فا دیز.m4a", 6),
    ("شبانگاهان_ دشتی فادیز.vocals.wav", 6),
    ("دلشکن _ دشتی می بمل.m4a", 3),
    ("شبانگاهان دشتی ''می''.m4a", 4),
    ("کعبه دلها _ دشتی ر.m4a", 2),
    ("کعبه‌ی دل‌ها_ دشتی فا دیز.pitch.json", 6),
    ("dashti in Fa diez.mp3", 6),
    ("exercise Si bemol.wav", 10),
    ("دلم می گیرد دشتی سل.m4a", 7),     # "می" earlier in the title is not the key
    ("my song.m4a", None),
    ("ba_man_sanama.labels.txt", None),
])
def test_key_from_name(name, index):
    from avaz.keys import key_from_name
    assert key_from_name(name) == index


def test_tonic_from_name_picks_the_octave_from_the_voice():
    from avaz.keys import tonic_from_name
    # The teacher's voice sits about a whole tone under the tonic.
    assert tonic_from_name("دشتی می بمل", 136.8) == pytest.approx(155.56, abs=0.01)
    assert tonic_from_name("دشتی فا دیز", 127.6) == pytest.approx(185.0, abs=0.01)
    assert tonic_from_name("دشتی ر", 128.4) == pytest.approx(146.83, abs=0.01)
    assert tonic_from_name("دشتی ر", 2 * 128.4) == pytest.approx(293.66, abs=0.01)  # an octave up
    assert tonic_from_name("no key here", 130.0) is None
    assert tonic_from_name("دشتی ر", None) is None
