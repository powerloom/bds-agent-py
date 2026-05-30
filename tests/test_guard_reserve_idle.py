"""Reserve idle timeout (no dip re-entry)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bds_agent.guard import (
    GuardConfig,
    normalize_guard_config,
    prepare_guard_run_state,
    reserve_idle_seconds,
    reserve_idle_timed_out,
    run_initial_entry_if_needed,
    sync_reserve_since,
)
from bds_agent.active_markets import WatchedPool


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


def test_prepare_guard_run_after_idle_timeout_resets_stale_timer() -> None:
    old = (datetime.now(tz=UTC) - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    state = {
        "position": "reserve",
        "guard_exit_reason": "reserve_idle_timeout",
        "reserve_since": old,
    }
    cfg = normalize_guard_config(GuardConfig(reserve_max_minutes=3.0, enter=True))
    state, new_leg = prepare_guard_run_state(state, cfg)
    assert new_leg is True
    assert state.get("guard_exit_reason") is None
    assert not reserve_idle_timed_out(cfg.reserve_max_minutes, state)


def test_prepare_without_enter_after_idle_keeps_reserve_skip() -> None:
    state = {
        "position": "reserve",
        "guard_exit_reason": "reserve_idle_timeout",
        "reserve_since": "2026-05-30T17:08:05Z",
    }
    cfg = normalize_guard_config(
        GuardConfig(reserve_max_minutes=3.0, enter=False),
    )
    state, new_leg = prepare_guard_run_state(state, cfg)
    assert new_leg is False
    assert state.get("guard_exit_reason") is None


def test_reset_state_sets_fresh_leg_and_clears_anchors(tmp_path, monkeypatch) -> None:
    from bds_agent import paths
    from bds_agent.guard_state import load_guard_state, reset_guard_state_for_new_leg

    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path)
    prev = {
        "pool_address": "0xE0554a476A092703abdB3Ef35c80e0D76d32939F",
        "pool_label": "USDC/WETH",
        "base_token": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "reference_entry_usd": 2024.0,
        "last_exit_usd": 2023.5,
        "take_profit_pct": 0.001,
        "reserve_since": "2026-05-30T17:08:05Z",
        "guard_exit_reason": "reserve_idle_timeout",
    }
    from bds_agent.guard_state import save_guard_state

    save_guard_state(prev, "r1")
    reset_guard_state_for_new_leg("r1")
    state = load_guard_state("r1")
    assert state.get("fresh_leg") is True
    assert state.get("last_exit_usd") is None
    assert state.get("reference_entry_usd") is None
    assert state.get("reserve_since") is None
    assert state.get("guard_exit_reason") is None


def test_allow_reserve_enter_after_reset() -> None:
    from bds_agent.guard import _allow_reserve_enter

    cfg = normalize_guard_config(GuardConfig(enter=True))
    state = {"fresh_leg": True, "reference_entry_usd": None, "last_exit_usd": None}
    assert _allow_reserve_enter(cfg, state, "reserve", begin_new_leg=False) is True


def test_new_leg_allows_initial_entry_from_reserve() -> None:
    cfg = GuardConfig(threshold_high=1.0, threshold_low=0.5, enter=True, dry_run=True)
    pool = WatchedPool(
        address="0xe0554a476a092703abdb3ef35c80e0d76d32939f",
        label="USDC/WETH",
        token0="0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        token1="0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
        base_idx=1,
        fee=500,
    )
    pos, result = run_initial_entry_if_needed(
        cfg,
        pool,
        position="reserve",
        price=2024.0,
        rpc_url="",
        private_key="",
        chain_id=1,
        allow_reserve_enter=True,
    )
    assert pos == "token"
    assert result is not None
    assert not result.get("skipped")
