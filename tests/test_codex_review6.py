"""Codex PR #1 review round 6 (2026-05-30)."""

from __future__ import annotations

import pytest

from bds_agent.active_markets import USDC_ADDRESS, WatchedPool
from bds_agent.cli import _trade_thresholds
from bds_agent.guard import GuardConfig, _allow_reserve_enter
from bds_agent.multi_pool import MultiPoolTracker


def test_invalid_price_source_rejected() -> None:
    with pytest.raises(ValueError, match="price-source"):
        _trade_thresholds(0.25, 2.0, 30.0, 5.0, 0.0, "usdc")


def test_refresh_watchlist_drops_stale_pools() -> None:
    p1 = WatchedPool("0xpool1", USDC_ADDRESS, "0xbase1", 1, "USDC/A")
    p2 = WatchedPool("0xpool2", USDC_ADDRESS, "0xbase2", 1, "USDC/B")
    tracker = MultiPoolTracker([p1, p2])
    assert len(tracker.pools) == 2
    p3 = WatchedPool("0xpool3", USDC_ADDRESS, "0xbase3", 1, "USDC/C")
    tracker.refresh_watchlist([p3])
    assert set(tracker.pools) == {"0xpool3"}


def test_refresh_watchlist_keeps_open_position_pool() -> None:
    p1 = WatchedPool("0xpool1", USDC_ADDRESS, "0xbase1", 1, "USDC/A")
    p2 = WatchedPool("0xpool2", USDC_ADDRESS, "0xbase2", 1, "USDC/B")
    tracker = MultiPoolTracker([p1, p2])
    p3 = WatchedPool("0xpool3", USDC_ADDRESS, "0xbase3", 1, "USDC/C")
    tracker.refresh_watchlist([p3], keep_pool_keys={"0xpool2"})
    assert set(tracker.pools) == {"0xpool2", "0xpool3"}


def test_pending_initial_entry_allows_reserve_enter() -> None:
    cfg = GuardConfig(enter=True)
    state: dict = {"reference_entry_usd": 2000.0}
    assert _allow_reserve_enter(
        cfg,
        state,
        "reserve",
        begin_new_leg=False,
        pending_initial_entry=True,
    )


def test_execute_entry_live_swap_failure_returns_none(monkeypatch) -> None:
    from bds_agent.active_markets import WatchedPool
    from bds_agent.trade import TraderConfig, _execute_entry_live

    pool = WatchedPool(
        "0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640",
        USDC_ADDRESS,
        "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        1,
        "USDC/WETH",
        fee=500,
    )
    monkeypatch.setattr(
        "bds_agent.evm_swap.enrich_watched_pool_fee",
        lambda _rpc, p: p,
    )
    monkeypatch.setattr(
        "bds_agent.trade.get_erc20_balance_human",
        lambda *_a, **_k: 0.0,
    )

    def _boom(*_a, **_k):
        raise RuntimeError("STF")

    monkeypatch.setattr("bds_agent.evm_swap.swap_usdc_to_token", _boom)
    state: dict = {"positions": []}
    out = __import__("rich.console", fromlist=["Console"]).Console(quiet=True)
    result = _execute_entry_live(
        TraderConfig(),
        state,
        pool,
        rpc="http://x",
        pk="0x" + "11" * 32,
        wallet="0x" + "22" * 20,
        chain_id=1,
        price=3000.0,
        epoch_i=1,
        out=out,
    )
    assert result is None
    assert not state.get("positions")


def test_reserve_enter_blocked_without_pending_or_fresh_leg() -> None:
    cfg = GuardConfig(enter=True)
    state = {"reference_entry_usd": 2000.0}
    assert not _allow_reserve_enter(
        cfg,
        state,
        "reserve",
        begin_new_leg=False,
        pending_initial_entry=False,
    )
