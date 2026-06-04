"""Codex PR #1 review round 13 (2026-06-04)."""

from __future__ import annotations

from bds_agent.active_markets import WatchedPool
from bds_agent.multi_pool import MultiPoolTracker, PoolEpochResult
from bds_agent.pulse import PulseBuffer, PulseDiagnostics, PulseThresholds, _usd_price_move
from bds_agent.guard_trade_sync import _record_guard_entry
from bds_agent import paths
from bds_agent.trader_state import load_trader_state, save_trader_state
from bds_agent.positions import normalize_trader_state, open_positions
from bds_agent.active_markets import WatchedPool as WP


def _weth_pool() -> WP:
    return WP(
        address="0xe0554a476a092703abdb3ef35c80e0d76d32939f",
        label="USDC/WETH",
        token0="0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        token1="0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
        base_idx=1,
        fee=500,
        base_decimals=18,
        quote_decimals=6,
    )


def test_usd_price_move_uses_stream_epoch_not_wall_clock() -> None:
    samples = [(100, 100.0), (110, 100.5), (120, 101.0), (126, 102.0)]
    pct, _, _ = _usd_price_move(samples, 300, 126)
    assert pct > 0


def test_pick_entry_longs_fills_slots_with_alts_then_weth() -> None:
    th = PulseThresholds()
    weth = WatchedPool(
        "0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640",
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        1,
        "USDC/WETH",
    )
    alt = WatchedPool(
        "0xpool2",
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "0x514910771AF9Ca656af840dff83E8264EcF986CA",
        1,
        "USDC/LINK",
    )
    d_weth = PulseDiagnostics(signal="LONG", price_pct=0.8, burst=4.0, imbalance_pct=60.0)
    d_alt = PulseDiagnostics(signal="LONG", price_pct=0.3, burst=2.5, imbalance_pct=40.0)
    results = [
        PoolEpochResult(pool=weth, added=1, price=3000.0, diag=d_weth, signal="LONG"),
        PoolEpochResult(pool=alt, added=1, price=15.0, diag=d_alt, signal="LONG"),
    ]
    picked = MultiPoolTracker.pick_entry_longs(results, th, open_pools=set(), limit=2)
    assert len(picked) == 2
    assert picked[0].pool.label == "USDC/LINK"
    assert picked[1].pool.label == "USDC/WETH"


def test_initial_entry_uses_fill_price_not_stale_reference(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path)
    pool = _weth_pool()
    save_trader_state({"positions": []}, "g-ref")
    _record_guard_entry(
        profile="g-ref",
        pool=pool,
        size_usd=25.0,
        dry_run=False,
        guard_state={"reference_entry_usd": 1990.0},
        action="initial_entry_buy",
        result={
            "action": "initial_entry_buy",
            "tx_hash": "0xfill",
            "size_usd": 25.0,
            "price_usd": 2050.0,
        },
        price=2050.0,
        rpc_url=None,
        private_key=None,
    )
    pos = open_positions(normalize_trader_state(load_trader_state("g-ref")))[0]
    assert float(pos["entry_price"]) == 2050.0
