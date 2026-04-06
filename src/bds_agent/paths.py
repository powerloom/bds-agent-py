from __future__ import annotations

import os
from pathlib import Path


def config_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "bds-agent"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "bds-agent"
    return Path.home() / ".config" / "bds-agent"


def credentials_path() -> Path:
    return config_dir() / "credentials.json"
