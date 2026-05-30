"""Pulse signal detection tests."""

from __future__ import annotations

import time

from bds_agent.pulse import PulseBuffer, PulseThresholds, detect_pulse, evaluate_pulse, normalize_trade


def _buy_trade(ts: int, usd: float, price: float, *, key: str) -> dict:
    """Buy WETH (base=token1): amount1 negative (WETH out of pool)."""
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


def _sell_trade(ts: int, usd: float, price: float, *, key: str) -> dict:
    """Sell WETH: amount1 positive (WETH into pool)."""
    return {
        "tradeType": "Swap",
        "data": {
            "block_timestamp": ts,
            "calculated_trade_amount_usd": usd,
            "calculated_token0_amount": usd / price,
            "calculated_token1_amount": 1.0,
            "amount0": -usd / price,
            "amount1": 1.0,
        },
        "log": {"transactionHash": key, "logIndex": 0},
    }


def test_detect_long_confluence() -> None:
    now = int(time.time())
    buf = PulseBuffer(pool_address="0xpool")
    th = PulseThresholds(
        price_move_pct=0.4,
        volume_burst_mult=2.0,
        flow_imbalance_pct=30.0,
        window_seconds=300,
        long_window_seconds=3600,
        cooldown_seconds=0,
        min_trades=3,
    )
    # Long-window baseline volume (outside the 5m signal window)
    for i in range(15):
        ts = now - 3200 + i * 120
        buf.ingest_epoch_trades(
            1000 + i,
            [_buy_trade(ts, 400.0, 3000.0, key=f"seed{i}")],
            now_ts=now,
        )
    # Short window: early third (lower price), late third (higher price), heavy buy flow
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
    signal = detect_pulse(buf, th, now_ts=now, now_ms=now * 1000)
    assert signal == "LONG"


def test_cooldown_blocks_repeat() -> None:
    now = int(time.time())
    buf = PulseBuffer(pool_address="0xpool", last_fire_ts_ms=now * 1000)
    th = PulseThresholds(cooldown_seconds=600, min_trades=1)
    buf.trades.append(normalize_trade(_buy_trade(now, 100.0, 3000.0, key="x"), epoch_id=1))
    assert detect_pulse(buf, th, now_ts=now, now_ms=now * 1000) is None


def test_cooldown_still_populates_window_metrics() -> None:
    now = int(time.time())
    buf = PulseBuffer(pool_address="0xpool", last_fire_ts_ms=now * 1000)
    th = PulseThresholds(cooldown_seconds=600, min_trades=1)
    for i in range(6):
        buf.ingest_epoch_trades(
            i,
            [_buy_trade(now - 60 + i, 200.0, 3000.0, key=f"c{i}")],
            now_ts=now,
        )
    diag = evaluate_pulse(buf, th, now_ts=now, now_ms=now * 1000)
    assert diag.signal is None
    assert diag.skip_reason == "cooldown"
    assert diag.short_count >= 5
    assert diag.burst > 0


def test_evaluate_pulse_warming_up() -> None:
    now = int(time.time())
    buf = PulseBuffer(pool_address="0xpool")
    th = PulseThresholds(min_trades=5, cooldown_seconds=0)
    buf.ingest_epoch_trades(
        1,
        [_buy_trade(now - 60, 100.0, 3000.0, key="a")],
        now_ts=now,
    )
    diag = evaluate_pulse(buf, th, now_ts=now, now_ms=now * 1000)
    assert diag.signal is None
    assert diag.skip_reason == "warming_up"
    assert diag.short_count == 1


def test_evaluate_pulse_gates_failed() -> None:
    now = int(time.time())
    buf = PulseBuffer(pool_address="0xpool")
    th = PulseThresholds(
        price_move_pct=0.4,
        volume_burst_mult=2.0,
        flow_imbalance_pct=30.0,
        cooldown_seconds=0,
        min_trades=3,
    )
    for i in range(3):
        buf.ingest_epoch_trades(
            10 + i,
            [_buy_trade(now - 120 + i * 10, 500.0, 3000.0, key=f"t{i}")],
            now_ts=now,
        )
    diag = evaluate_pulse(buf, th, now_ts=now, now_ms=now * 1000)
    assert diag.signal is None
    assert diag.skip_reason == "gates_failed"
    assert diag.short_count >= 3


def test_trader_state_roundtrip(tmp_path, monkeypatch) -> None:
    from bds_agent import paths
    from bds_agent.trader_state import (
        append_trade,
        load_trader_state,
        load_trades,
        save_trader_state,
        summarize_trades,
    )

    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path)
    monkeypatch.setenv("BDS_AGENT_PROFILE", "trading")

    state = {"position": "LONG", "entry_price": 3000.0}
    save_trader_state(state, "trading")
    loaded = load_trader_state("trading")
    assert loaded["position"] == "LONG"
    assert loaded["entry_price"] == 3000.0

    append_trade({"type": "EXIT", "pnl_usd": 1.5}, "trading")
    append_trade({"type": "EXIT", "pnl_usd": -0.5}, "trading")
    trades = load_trades("trading")
    assert len(trades) == 2
    summary = summarize_trades(trades)
    assert summary["total_trades"] == 2
    assert summary["wins"] == 1
    assert summary["losses"] == 1
    assert summary["total_pnl_usd"] == 1.0


def test_dry_run_position_detected_and_cleared_for_live() -> None:
    from bds_agent.trader_state import (
        default_trader_state,
        is_dry_run_position,
        prepare_live_trader_state,
        reconcile_live_trader_state,
    )

    paper = {
        **default_trader_state(),
        "position": "LONG",
        "entry_tx": "dry-run",
        "entry_pool": "0xabc",
    }
    assert is_dry_run_position(paper) is True
    live = reconcile_live_trader_state(paper, live_mode=True)
    assert live["position"] is None
    assert live["entry_pool"] is None
    assert live["reentry_blocked_until"] is None
    assert reconcile_live_trader_state(paper, live_mode=False) == paper


def test_prepare_live_keeps_live_position_when_paper_also_open() -> None:
    from bds_agent.positions import open_positions, strip_dry_run_positions
    from bds_agent.trader_state import prepare_live_trader_state

    live_pool = "0x1111111111111111111111111111111111111111"
    paper_pool = "0x2222222222222222222222222222222222222222"

    def _mixed_state() -> dict:
        return {
            "positions": [
                {
                    "entry_pool": live_pool,
                    "entry_label": "LIVE",
                    "entry_token": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
                    "entry_token0": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
                    "entry_token1": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
                    "entry_base_idx": 1,
                    "entry_fee": 500,
                    "entry_base_decimals": 18,
                    "entry_price": 2000.0,
                    "entry_tx": "0xlive",
                    "dry_run": False,
                },
                {
                    "entry_pool": paper_pool,
                    "entry_label": "PAPER",
                    "entry_token": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
                    "entry_token0": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
                    "entry_token1": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
                    "entry_base_idx": 1,
                    "entry_fee": 500,
                    "entry_base_decimals": 18,
                    "entry_price": 2100.0,
                    "entry_tx": "dry-run",
                    "dry_run": True,
                },
            ],
        }

    stripped, removed = strip_dry_run_positions(_mixed_state())
    assert removed == 1
    assert len(open_positions(stripped)) == 1
    assert stripped["positions"][0]["entry_pool"] == live_pool

    prepared, notes = prepare_live_trader_state(_mixed_state())
    assert len(open_positions(prepared)) == 1
    assert prepared["positions"][0]["entry_pool"] == live_pool
    assert any("dry-run" in n.lower() and "kept" in n.lower() for n in notes)


def test_strip_dry_run_clears_per_pool_cooldown() -> None:
    from bds_agent.positions import strip_dry_run_positions

    paper_pool = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    state = {
        "positions": [
            {
                "entry_pool": paper_pool,
                "entry_label": "PAPER",
                "entry_token": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
                "entry_token0": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
                "entry_token1": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
                "entry_base_idx": 1,
                "entry_fee": 500,
                "entry_base_decimals": 18,
                "entry_price": 2100.0,
                "entry_tx": "dry-run",
                "dry_run": True,
            },
        ],
        "pool_reentry_blocked": {paper_pool.lower(): "2099-01-01T00:00:00Z"},
    }
    stripped, removed = strip_dry_run_positions(state)
    assert removed == 1
    assert stripped.get("pool_reentry_blocked", {}).get(paper_pool.lower()) is None


def test_prepare_live_clears_dry_run_cooldown(tmp_path, monkeypatch) -> None:
    from bds_agent import paths
    from bds_agent.trader_state import (
        append_trade,
        default_trader_state,
        prepare_live_trader_state,
        save_trader_state,
    )

    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path)
    monkeypatch.setenv("BDS_AGENT_PROFILE", "trading")

    state = {
        **default_trader_state(),
        "reentry_blocked_until": "2099-01-01T00:00:00Z",
    }
    save_trader_state(state, "trading")
    append_trade({"type": "EXIT", "dry_run": True, "pnl_usd": 0.25}, "trading")

    prepared, notes = prepare_live_trader_state(state, "trading")
    assert prepared["reentry_blocked_until"] is None
    assert notes
