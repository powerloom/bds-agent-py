"""Reserve idle timeout (no dip re-entry)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bds_agent.guard import (
    GuardConfig,
    normalize_guard_config,
    reserve_idle_seconds,
    reserve_idle_timed_out,
    sync_reserve_since,
)


def test_reserve_idle_not_timed_out_before_limit() -> None:
    state = {
        "position": "reserve",
        "reserve_since": (datetime.now(tz=UTC) - timedelta(minutes=5)).isoformat().replace(
            "+00:00",
            "Z",
        ),
    }
    cfg = normalize_guard_config(GuardConfig(reserve_max_minutes=30.0, enter=True))
    assert not reserve_idle_timed_out(cfg.reserve_max_minutes, state)
    assert reserve_idle_seconds(state) is not None
    assert reserve_idle_seconds(state) < 30 * 60


def test_reserve_idle_timed_out_after_limit() -> None:
    state = {
        "position": "reserve",
        "reserve_since": (datetime.now(tz=UTC) - timedelta(minutes=31)).isoformat().replace(
            "+00:00",
            "Z",
        ),
    }
    assert reserve_idle_timed_out(30.0, state)


def test_reserve_idle_disabled_when_zero() -> None:
    state = {
        "position": "reserve",
        "reserve_since": (datetime.now(tz=UTC) - timedelta(hours=5)).isoformat().replace(
            "+00:00",
            "Z",
        ),
    }
    assert not reserve_idle_timed_out(0.0, state)


def test_sync_reserve_since_clears_on_token() -> None:
    state = {"position": "reserve", "reserve_since": "2026-05-29T17:00:00Z"}
    sync_reserve_since(state, "token")
    assert "reserve_since" not in state
