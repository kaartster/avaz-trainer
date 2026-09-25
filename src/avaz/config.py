"""Load settings.yaml and locate project folders.

The project root is found by walking up from this file until a folder containing
``config/settings.yaml`` is found. That keeps the CLI usable from any working directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def project_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "config" / "settings.yaml").exists():
            return parent
    return Path.cwd()


def config_dir() -> Path:
    return project_root() / "config"


def data_dir() -> Path:
    return project_root() / "data"


def load_settings(path: Path | None = None) -> dict[str, Any]:
    path = path or (config_dir() / "settings.yaml")
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


# ---------------------------------------------------------------- per-song settings
#
# Some choices belong to one recording, not to the whole app: its tonic, and
# whether the teacher sang it in my own key. They live in ``song.yaml`` inside
# the song's phrase folder (data/phrases/<song>/), which is where both song mode
# and phrase practice look, so they only have to be set once.

SONG_CONFIG_NAME = "song.yaml"


def song_config_path(folder: str | Path) -> Path:
    return Path(folder) / SONG_CONFIG_NAME


def load_song_config(folder: str | Path) -> dict[str, Any]:
    path = song_config_path(folder)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def save_song_config(folder: str | Path, **updates) -> Path:
    """Merge ``updates`` into the folder's song.yaml. ``None`` values are ignored."""
    cfg = load_song_config(folder)
    cfg.update({k: v for k, v in updates.items() if v is not None})
    path = song_config_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, allow_unicode=True, sort_keys=True)
    return path


def resolve_tonics(song_cfg: dict, settings: dict, curve_tonic: float | None = None,
                   my_tonic: float | None = None, teacher_tonic: float | None = None,
                   same_key: bool | None = None) -> tuple[float | None, float | None, bool]:
    """Decide ``(teacher_tonic, my_tonic, same_key)`` for one practice session.

    Explicit arguments win, then the song's song.yaml, then the recording's own
    curve, then settings.yaml. With ``same_key`` the teacher sang in my range, so
    both curves use the teacher's tonic: my pitch is compared as it is, never
    transposed. ``teacher_tonic`` comes back None when nothing is known, and the
    caller then estimates it from the recording.
    """
    tonic_settings = settings.get("tonic", {})
    same = bool(song_cfg.get("same_key", False)) if same_key is None else bool(same_key)
    teacher = (teacher_tonic or song_cfg.get("teacher_tonic_hz") or curve_tonic
               or tonic_settings.get("teacher_hz"))
    teacher = float(teacher) if teacher else None
    if same:
        mine = teacher
    else:
        mine = my_tonic or tonic_settings.get("mine_hz") or teacher
        mine = float(mine) if mine else None
    return teacher, mine, same
