"""The song library behind ``avaz gui``: which recordings exist and how far along each is.

A song is one original recording in ``data/teacher/``. Around it the other
commands leave files with the same name: ``<name>.vocals.wav`` from vocal
separation, ``<name>.vocals.pitch.json`` (or ``<name>.pitch.json``) from the pitch
analysis, ``data/phrases/<name>/`` with its song.yaml and saved phrases, and
``data/attempts/<name>/`` with my recordings and their scores. This module only
reads those files, so the library always matches what the command line did.
"""

from __future__ import annotations

import json
import math
import shutil
from dataclasses import dataclass, field
from pathlib import Path

AUDIO_SUFFIXES = (".m4a", ".mp3", ".opus", ".ogg", ".wav", ".flac", ".aac")
DERIVED_SUFFIXES = (".vocals.wav", ".accompaniment.wav")


@dataclass
class Progress:
    attempts: int = 0
    phrases: int = 0              # phrases with at least one attempt
    last_practiced: str = ""      # timestamp of the newest attempt, YYYYMMDD_HHMMSS
    recent_pct: float = math.nan  # mean "% within tolerance" of the last 10 attempts

    @property
    def last_day(self) -> str:
        s = self.last_practiced
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}" if len(s) >= 8 else ""


@dataclass
class Song:
    name: str
    original: Path
    vocals: Path | None
    phrase_dir: Path
    attempts_dir: Path
    config: dict = field(default_factory=dict)
    phrase_count: int = 0

    @property
    def practice_path(self) -> Path:
        """The file to practice with: the separated voice if it exists."""
        return self.vocals or self.original

    @property
    def curve_path(self) -> Path:
        from .pitch_offline import curve_path_for
        return curve_path_for(self.practice_path)

    @property
    def analyzed(self) -> bool:
        return self.curve_path.exists()

    def progress(self) -> Progress:
        return read_progress(self.attempts_dir)


def is_original_recording(path: Path) -> bool:
    name = path.name.lower()
    return (path.is_file() and name.endswith(AUDIO_SUFFIXES)
            and not name.endswith(DERIVED_SUFFIXES))


def phrase_files(folder: Path) -> list[Path]:
    """Phrase WAVs in a song's phrase folder, without generated tracks."""
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("*.wav") if not p.name.startswith("call_response"))


def discover_songs(teacher_dir: Path, phrases_dir: Path, attempts_dir: Path) -> list[Song]:
    from .config import load_song_config
    songs = []
    if not Path(teacher_dir).is_dir():
        return songs
    for path in sorted(Path(teacher_dir).iterdir(), key=lambda p: p.name):
        if not is_original_recording(path):
            continue
        stem = path.stem
        vocals = path.with_name(stem + ".vocals.wav")
        folder = Path(phrases_dir) / stem
        songs.append(Song(name=stem, original=path,
                          vocals=vocals if vocals.exists() else None,
                          phrase_dir=folder, attempts_dir=Path(attempts_dir) / stem,
                          config=load_song_config(folder),
                          phrase_count=len(phrase_files(folder))))
    return songs


def read_progress(song_attempts_dir: Path) -> Progress:
    """Summarize every scored attempt of a song (all its phrase folders)."""
    entries = []
    folders = 0
    root = Path(song_attempts_dir)
    if root.is_dir():
        for hist in sorted(root.glob("*/history.json")):
            try:
                with open(hist, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError):
                continue
            if data:
                folders += 1
            for stem, e in data.items():
                entries.append((str(e.get("recorded_at") or stem), e.get("pct_within")))
    if not entries:
        return Progress()
    entries.sort()
    recent = [float(p) for _, p in entries[-10:] if isinstance(p, (int, float)) and math.isfinite(p)]
    return Progress(attempts=len(entries), phrases=folders, last_practiced=entries[-1][0],
                    recent_pct=sum(recent) / len(recent) if recent else math.nan)


def import_recording(src: Path, teacher_dir: Path) -> Path:
    """Copy a recording into the teacher folder. Refuses to overwrite an existing file."""
    src = Path(src)
    if not src.name.lower().endswith(AUDIO_SUFFIXES):
        raise ValueError(f"{src.name} is not an audio file this app can read")
    dest = Path(teacher_dir) / src.name
    if dest.exists():
        if dest.resolve() == src.resolve():
            return dest
        raise FileExistsError(f"{dest.name} is already in the library")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


@dataclass
class SongSetup:
    """Everything song mode needs, decided once for both ``avaz song`` and ``avaz gui``."""
    curve: object                 # PitchCurve of the teacher, cents against teacher_tonic
    audio: object                 # np.ndarray at the engine sample rate
    teacher_tonic: float
    my_tonic: float
    same_key: bool
    start_seconds: float          # intro cut


def name_tonic(name: str, f0_hz) -> float | None:
    """The teacher's tonic from the key in the recording's name ("... دشتی می بمل"),
    placed in the octave where this recording's voice sits. None without a key."""
    import numpy as np
    from .keys import tonic_from_name
    f0 = np.asarray(f0_hz, dtype=float)
    f0 = f0[np.isfinite(f0) & (f0 > 0)]
    return tonic_from_name(name, float(np.median(f0))) if f0.size else None


def prepare_song(src: Path, out_dir: Path, settings: dict, sample_rate: int,
                 my_tonic: float | None = None, teacher_tonic=None, log=print) -> SongSetup:
    """Resolve the tonics, load (or make) the pitch curve and the audio.

    The teacher's tonic comes from song.yaml, else from the key in the file name,
    else from the recording itself. ``teacher_tonic`` may be a number or
    "auto"/"final" to override all of that.
    """
    from .audio_io import load_audio
    from .config import load_song_config, resolve_tonics
    from .pitch_offline import load_or_analyze

    song_cfg = load_song_config(out_dir)
    estimate = teacher_tonic if isinstance(teacher_tonic, str) else "auto"
    curve = load_or_analyze(Path(src), settings, estimate, log=log)
    if isinstance(teacher_tonic, str):
        teacher, mine, same_key = resolve_tonics(song_cfg, settings, my_tonic=my_tonic,
                                                 teacher_tonic=curve.tonic_hz)
    else:
        teacher, mine, same_key = resolve_tonics(
            song_cfg, settings, my_tonic=my_tonic, teacher_tonic=teacher_tonic,
            name_tonic=name_tonic(Path(src).name, curve.f0_hz))
    if teacher and abs(float(teacher) - curve.tonic_hz) > 1e-6:
        curve = curve.with_tonic(float(teacher))
    if same_key or not mine:
        mine = curve.tonic_hz
    y, _ = load_audio(src, sr=sample_rate)
    return SongSetup(curve=curve, audio=y, teacher_tonic=float(curve.tonic_hz),
                     my_tonic=float(mine), same_key=bool(same_key),
                     start_seconds=float(song_cfg.get("intro_end_seconds") or 0.0))
