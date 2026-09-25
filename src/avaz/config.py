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
