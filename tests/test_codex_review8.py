"""Codex PR #1 review round 8 (2026-05-31)."""

from __future__ import annotations

import asyncio

import pytest

from bds_agent.active_markets import USDC_ADDRESS, WatchedPool
from bds_agent.cli import _normalize_price_source, _trade_config
from bds_agent.client import BdsClientError, stream
from bds_agent.trade import _merge_watchlist_open_positions


def test_normalize_price_source_strips_and_lowercases() -> None:
    assert _normalize_price_source(" USD ") == "usd"
    assert _normalize_price_source("Trades") == "trades"


def test_trade_config_stores_normalized_price_source() -> None:
    cfg = _trade_config(
        pair="USDC-WETH",
        size=25.0,
        slippage=0.005,
        dry_run=True,
        profile=None,
        price_move=0.25,
        volume_burst=2.0,
        flow_imbalance=30.0,
        window_minutes=5.0,
        reentry_cooldown_minutes=0.0,
        signal_cooldown_minutes=0.0,
        daily_loss_limit=50.0,
        exit_signal_reversal=True,
        exit_time_based=False,
        exit_hold_minutes=60.0,
        exit_trailing_stop=False,
        exit_trailing_pct=0.02,
        exit_take_profit=False,
        exit_take_profit_pct=0.05,
        exit_stop_loss=False,
        exit_stop_loss_pct=0.03,
        price_source=" USD ",
    )
    assert cfg.price_source == "usd"
    assert cfg.thresholds is not None
    assert cfg.thresholds.price_source == "usd"


def test_merge_watchlist_includes_open_position_pool() -> None:
    on_list = WatchedPool(
        "0xpool1",
        USDC_ADDRESS,
        "0xbase1",
        1,
        "USDC/A",
    )
    held = WatchedPool(
        "0xstale",
        USDC_ADDRESS,
        "0xbase2",
        1,
        "USDC/B",
        fee=500,
    )
    state = {
        "positions": [
            {
                "entry_pool": held.address,
                "entry_token0": held.token0,
                "entry_token1": held.token1,
                "entry_base_idx": held.base_idx,
                "entry_label": held.label,
                "entry_fee": held.fee,
                "entry_base_decimals": held.base_decimals,
            },
        ],
    }
    merged = _merge_watchlist_open_positions([on_list], state)
    keys = {p.address.lower() for p in merged}
    assert keys == {"0xpool1", "0xstale"}


def test_stream_bds_client_error_does_not_reconnect(monkeypatch) -> None:
    async def _fail(*_a, **_k):
        raise BdsClientError("SSE failed HTTP 401: unauthorized")
        yield  # pragma: no cover

    monkeypatch.setattr(
        "bds_agent.client._stream_single_connection",
        _fail,
    )
    slept: list[float] = []

    async def _no_sleep(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr("bds_agent.client.asyncio.sleep", _no_sleep)

    async def _consume() -> None:
        async for _chunk in stream(
            "http://example.invalid",
            "/mpp/stream/allTrades",
            "bad-key",
            reconnect=True,
            max_reconnects=0,
        ):
            pass

    with pytest.raises(BdsClientError, match="401"):
        asyncio.run(_consume())
    assert slept == []
