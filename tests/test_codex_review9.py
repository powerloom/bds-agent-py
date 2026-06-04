"""Codex PR #1 review round 9 (2026-05-31)."""

from __future__ import annotations

import time

from bds_agent.guard import sync_reserve_since
from bds_agent.pulse import PulseBuffer, PulseThresholds, evaluate_pulse
from bds_agent.trade import _price_usable


def _buy_trade(ts: int, usd: float, price: float, *, key: str) -> dict:
    return {
        "tradeType": "Swap",
        "data": {
            "block_timestamp": ts,
            "calculated_trade_amount_usd": usd,
            "calculated_token0_amount": usd / price,
            "calculated_token1_amount": 1.0,
            "amount0": usd / price,
            "amount1": -1.0,
        },
        "log": {"transactionHash": key, "logIndex": 0},
    }


def test_sync_reserve_since_uses_now_not_updated_at() -> None:
    state = {"updated_at": "2020-01-01T00:00:00Z"}
    sync_reserve_since(state, "reserve")
    assert state["reserve_since"] != "2020-01-01T00:00:00Z"
    assert state["reserve_since"].endswith("Z")


def test_price_usable() -> None:
    assert not _price_usable(None)
    assert not _price_usable(0)
    assert _price_usable(3000.0)


def test_signal_does_not_start_cooldown_until_consumed() -> None:
    now = int(time.time())
    buf = PulseBuffer(pool_address="0xpool")
    th = PulseThresholds(
        price_move_pct=0.4,
        volume_burst_mult=2.0,
        flow_imbalance_pct=30.0,
        window_seconds=300,
        long_window_seconds=3600,
        cooldown_seconds=600,
        min_trades=3,
    )
    for i in range(15):
        ts = now - 3200 + i * 120
        buf.ingest_epoch_trades(
            1000 + i,
            [_buy_trade(ts, 400.0, 3000.0, key=f"seed{i}")],
            now_ts=now,
        )
    early = [
        _buy_trade(now - 280, 8000.0, 3000.0, key="e0"),
        _buy_trade(now - 260, 8000.0, 3005.0, key="e1"),
        _buy_trade(now - 240, 8000.0, 3010.0, key="e2"),
    ]
    late = [
        _buy_trade(now - 80, 8000.0, 3040.0, key="l0"),
        _buy_trade(now - 60, 8000.0, 3045.0, key="l1"),
        _buy_trade(now - 40, 8000.0, 3050.0, key="l2"),
    ]
    buf.ingest_epoch_trades(2000, early + late, now_ts=now)
    diag1 = evaluate_pulse(buf, th, now_ts=now, now_ms=now * 1000)
    assert diag1.signal == "LONG"
    assert buf.last_fire_ts_ms == 0
    diag2 = evaluate_pulse(buf, th, now_ts=now, now_ms=now * 1000 + 1)
    assert diag2.signal == "LONG"
    buf.consume_signal(now_ms=now * 1000)
    diag3 = evaluate_pulse(buf, th, now_ts=now, now_ms=now * 1000 + 2)
    assert diag3.signal is None
    assert diag3.skip_reason == "cooldown"
