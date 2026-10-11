import pytest

from avaz.config import load_song_config, save_song_config, song_config_path, resolve_tonics

SETTINGS = {"tonic": {"teacher_hz": 185.0, "mine_hz": 146.8}}


def test_song_config_round_trip_and_merge(tmp_path):
    assert load_song_config(tmp_path) == {}
    save_song_config(tmp_path, same_key=True, teacher_tonic_hz=132.0)
    assert load_song_config(tmp_path) == {"same_key": True, "teacher_tonic_hz": 132.0}
    save_song_config(tmp_path, teacher_tonic_hz=None, same_key=False)   # None leaves a value alone
    assert load_song_config(tmp_path) == {"same_key": False, "teacher_tonic_hz": 132.0}
    assert song_config_path(tmp_path).name == "song.yaml"


def test_resolve_tonics_defaults_transpose_to_my_tonic():
    teacher, mine, same = resolve_tonics({}, SETTINGS)
    assert (teacher, mine, same) == (185.0, 146.8, False)


def test_resolve_tonics_same_key_uses_teacher_tonic_for_me():
    teacher, mine, same = resolve_tonics({"same_key": True, "teacher_tonic_hz": 132.0}, SETTINGS)
    assert (teacher, mine, same) == (132.0, 132.0, True)


def test_resolve_tonics_priority_argument_then_song_then_curve_then_settings():
    cfg = {"teacher_tonic_hz": 132.0}
    assert resolve_tonics(cfg, SETTINGS, curve_tonic=150.0, teacher_tonic=140.0)[0] == 140.0
    assert resolve_tonics(cfg, SETTINGS, curve_tonic=150.0)[0] == 132.0
    assert resolve_tonics({}, SETTINGS, curve_tonic=150.0)[0] == 150.0
    assert resolve_tonics({}, SETTINGS)[0] == 185.0
    assert resolve_tonics({}, {})[0] is None


def test_resolve_tonics_argument_overrides_song_key_choice():
    cfg = {"same_key": True, "teacher_tonic_hz": 132.0}
    teacher, mine, same = resolve_tonics(cfg, SETTINGS, same_key=False)
    assert same is False and mine == 146.8
    teacher, mine, same = resolve_tonics({}, SETTINGS, my_tonic=150.0)
    assert mine == 150.0


def test_resolve_tonics_uses_the_key_chosen_for_the_song():
    teacher, mine, same = resolve_tonics({"my_tonic_hz": 164.8}, SETTINGS)
    assert mine == 164.8 and same is False
    assert resolve_tonics({"my_tonic_hz": 164.8}, SETTINGS, my_tonic=150.0)[1] == 150.0
    # Singing in the teacher's key ignores a key chosen earlier.
    assert resolve_tonics({"my_tonic_hz": 164.8, "same_key": True, "teacher_tonic_hz": 167.0},
                          SETTINGS)[1] == 167.0


def test_user_prefs_round_trip_keeps_none(tmp_path):
    from avaz.config import load_user_prefs, save_user_prefs
    path = tmp_path / "user.yaml"
    assert load_user_prefs(path) == {}
    save_user_prefs({"my_tonic_hz": 146.8, "input_device": None}, path)
    save_user_prefs({"scale": "dashti"}, path)
    assert load_user_prefs(path) == {"my_tonic_hz": 146.8, "input_device": None, "scale": "dashti"}
