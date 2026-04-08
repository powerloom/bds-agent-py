from __future__ import annotations

import os
import re
from pathlib import Path

_PROFILE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def config_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "bds-agent"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "bds-agent"
    return Path.home() / ".config" / "bds-agent"


def profiles_dir() -> Path:
    return config_dir() / "profiles"


def active_profile_path() -> Path:
    """Plain-text file: one line, profile name for `profiles/<name>.json`."""
    return config_dir() / "active_profile"


def tempo_env_path_for_profile(profile_name: str) -> Path:
    """Per-profile Tempo env: profiles/<name>.tempo.env (parallel to <name>.json)."""
    return profiles_dir() / f"{sanitize_profile_name(profile_name)}.tempo.env"


def sanitize_profile_name(name: str) -> str:
    s = name.strip()
    if not _PROFILE_NAME_RE.match(s):
        raise ValueError(
            "Profile name must be 1–64 characters: letters, digits, underscore, hyphen.",
        )
    return s


def default_profile_slug(agent_name: str) -> str:
    """Derive a safe default profile label from the agent name."""
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", agent_name.strip()).strip("-")
    if not s:
        return "default"
    return s[:64]

