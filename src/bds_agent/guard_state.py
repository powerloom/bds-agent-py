"""Persistent JSON state for Threshold Guard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bds_agent.credentials import resolve_profile_name
from bds_agent.paths import profiles_dir, sanitize_profile_name


def guard_state_path(profile: str | None = None) -> Path:
    raw = profile or resolve_profile_name() or "default"
    name = sanitize_profile_name(str(raw).strip())
    return profiles_dir() / f"{name}.guard.json"


def default_guard_state() -> dict[str, Any]:
    return {
        "position": "token",
        "pool_address": None,
        "pool_label": None,
        "base_token": None,
        "pricing_mode": None,
        "reference_entry_usd": None,
        "last_exit_usd": None,
        "take_profit_pct": None,
        "stop_loss_pct": None,
        "reentry_retrace_pct": None,
        "threshold_high": None,
        "threshold_low": None,
        "last_price_usd": None,
        "last_block": None,
        "last_action": None,
        "pending_action": None,
        "pending_fail_count": 0,
        "last_execute_error": None,
        "updated_at": None,
        "reserve_since": None,
        "reserve_max_minutes": None,
        "guard_exit_reason": None,
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


def reset_guard_state_for_new_leg(
    profile: str | None = None,
    *,
    keep_pool: bool = True,
) -> dict[str, Any]:
    """
    Clear a completed guard cycle so ``guard run --enter`` can open a fresh leg.

    Keeps pool, token, and %% bracket settings only (not old exit/entry anchors).
    """
    prev = load_guard_state(profile)
    state = default_guard_state()
    if keep_pool:
        for key in (
            "pool_address",
            "pool_label",
            "base_token",
            "pricing_mode",
            "take_profit_pct",
            "stop_loss_pct",
            "reentry_retrace_pct",
            "reserve_max_minutes",
        ):
            if prev.get(key) is not None:
                state[key] = prev[key]
    state["position"] = "reserve"
    state["fresh_leg"] = True
    state.pop("threshold_high", None)
    state.pop("threshold_low", None)
    state["updated_at"] = None
    save_guard_state(state, profile)
    return state
