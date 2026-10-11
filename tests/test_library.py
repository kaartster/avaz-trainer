import json
import math

import pytest

from avaz.library import discover_songs, import_recording, read_progress


def touch(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_discover_songs_groups_derived_files(tmp_path):
    teacher, phrases, attempts = tmp_path / "teacher", tmp_path / "phrases", tmp_path / "attempts"
    touch(teacher / "song a.m4a")
    touch(teacher / "song a.vocals.wav")
    touch(teacher / "song a.accompaniment.wav")
    touch(teacher / "song a.vocals.pitch.json")
    touch(teacher / "song b.mp3")
    touch(teacher / "notes.txt")
    touch(phrases / "song a" / "song.yaml", "same_key: true\nteacher_tonic_hz: 167.0\n")
    touch(phrases / "song a" / "live_01.wav")
    touch(phrases / "song a" / "call_response.wav")

    songs = discover_songs(teacher, phrases, attempts)
    assert [s.name for s in songs] == ["song a", "song b"]
    a, b = songs
    assert a.practice_path.name == "song a.vocals.wav" and a.analyzed
    assert a.config == {"same_key": True, "teacher_tonic_hz": 167.0}
    assert a.phrase_count == 1
    assert a.attempts_dir == attempts / "song a"
    assert b.vocals is None and b.practice_path.name == "song b.mp3" and not b.analyzed
    assert b.config == {} and b.phrase_count == 0
    assert discover_songs(tmp_path / "missing", phrases, attempts) == []


def test_read_progress_summarizes_all_phrases(tmp_path):
    assert read_progress(tmp_path / "none").attempts == 0
    hist1 = {f"20261001_1000{i:02d}": {"pct_within": 10.0 * i, "recorded_at": f"20261001_1000{i:02d}"}
             for i in range(8)}
    hist2 = {"20261003_090000": {"pct_within": 90.0}, "20261002_090000": {"pct_within": float("nan")}}
    touch(tmp_path / "live_01" / "history.json", json.dumps(hist1))
    touch(tmp_path / "live_02" / "history.json", json.dumps(hist2))
    p = read_progress(tmp_path)
    assert p.attempts == 10 and p.phrases == 2
    assert p.last_practiced == "20261003_090000" and p.last_day == "2026-10-03"
    # Last 10 attempts, NaN skipped: 0..70 (step 10) and 90.
    assert p.recent_pct == pytest.approx((sum(range(0, 80, 10)) + 90) / 9)
    assert math.isnan(read_progress(tmp_path / "empty").recent_pct)


def test_import_recording_copies_and_refuses_overwrite(tmp_path):
    src = touch(tmp_path / "in" / "new song.m4a", "audio")
    dest = import_recording(src, tmp_path / "teacher")
    assert dest.read_text(encoding="utf-8") == "audio"
    assert import_recording(dest, tmp_path / "teacher") == dest      # already there: fine
    with pytest.raises(FileExistsError):
        import_recording(touch(tmp_path / "other" / "new song.m4a"), tmp_path / "teacher")
    with pytest.raises(ValueError):
        import_recording(touch(tmp_path / "in" / "notes.txt"), tmp_path / "teacher")
