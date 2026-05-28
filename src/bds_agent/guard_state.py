"""Persistent JSON state for Threshold Guard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bds_agent.credentials import resolve_profile_name
from bds_agent.paths import profiles_dir


def guard_state_path(profile: str | None = None) -> Path:
    name = profile or resolve_profile_name() or "default"
    return profiles_dir() / f"{name}.guard.json"


def default_guard_state() -> dict[str, Any]:
    return {
        "position": "token",
        "pool_address": None,
        "pool_label": None,
        "base_token": None,
        "threshold_high": None,
        "threshold_low": None,
        "last_price_usd": None,
        "last_epoch": None,
        "last_block": None,
        "bds_project": None,
        "last_action": None,
        "pending_action": None,
        "pending_fail_count": 0,
        "last_execute_error": None,
        "updated_at": None,
    }


def load_guard_state(profile: str | None = None) -> dict[str, Any]:
    path = guard_state_path(profile)
    if not path.is_file():
        return default_guard_state()
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default_guard_state()
    if not isinstance(data, dict):
        return default_guard_state()
    base = default_guard_state()
    base.update(data)
    return base


def save_guard_state(state: dict[str, Any], profile: str | None = None) -> None:
    path = guard_state_path(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n")
