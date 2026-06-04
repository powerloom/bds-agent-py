"""Multi-pool Pulse tracker tests."""

from __future__ import annotations

import time

from bds_agent.active_markets import USDC_ADDRESS, watched_pool_from_entry
from bds_agent.multi_pool import MultiPoolTracker, confluence_score
from bds_agent.pulse import PulseThresholds


def test_watched_pool_from_entry_usdc_token1() -> None:
    entry = {
        "pool_address": "0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640",
        "frequency": 10,
        "metadata": {
            "token0": {"address": USDC_ADDRESS, "symbol": "USDC", "decimals": 6},
            "token1": {"address": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", "symbol": "WETH", "decimals": 18},
        },
    }
    wp = watched_pool_from_entry(entry)
    assert wp is not None
    assert wp.base_idx == 1
    assert wp.label == "USDC/WETH"


def test_watched_pool_skips_non_usdc() -> None:
    entry = {
        "pool_address": "0xabc",
        "frequency": 5,
        "metadata": {
            "token0": {"address": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", "symbol": "WETH"},
            "token1": {"address": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599", "symbol": "WBTC"},
        },
    }
    assert watched_pool_from_entry(entry) is None


def test_pick_best_long_by_score() -> None:
    from bds_agent.active_markets import WatchedPool
    from bds_agent.multi_pool import PoolEpochResult
    from bds_agent.pulse import PulseDiagnostics

    th = PulseThresholds()
    p1 = WatchedPool("0xpool1", USDC_ADDRESS, "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", 1, "USDC/WETH")
    p2 = WatchedPool("0xpool2", USDC_ADDRESS, "0x514910771AF9Ca656af840dff83E8264EcF986CA", 1, "USDC/LINK")
    d1 = PulseDiagnostics(signal="LONG", price_pct=0.3, burst=2.5, imbalance_pct=40.0)
    d2 = PulseDiagnostics(signal="LONG", price_pct=0.5, burst=3.0, imbalance_pct=50.0)
    r1 = PoolEpochResult(pool=p1, added=1, price=3000.0, diag=d1, signal="LONG")
    r2 = PoolEpochResult(pool=p2, added=2, price=15.0, diag=d2, signal="LONG")
    assert confluence_score(d2, th) > confluence_score(d1, th)
    best = MultiPoolTracker.pick_best_long([r1, r2], th)
    assert best is not None
    assert best.pool.label == "USDC/LINK"


def test_pick_best_long_prefers_alt_over_weth() -> None:
    from bds_agent.active_markets import WatchedPool
    from bds_agent.multi_pool import MultiPoolTracker, PoolEpochResult
    from bds_agent.pulse import PulseDiagnostics

    th = PulseThresholds()
    weth_pool = WatchedPool(
        "0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640",
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        1,
        "USDC/WETH",
    )
    alt_pool = WatchedPool(
        "0xpool2",
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "0x514910771AF9Ca656af840dff83E8264EcF986CA",
        1,
        "USDC/LINK",
    )
    d_weth = PulseDiagnostics(signal="LONG", price_pct=0.8, burst=4.0, imbalance_pct=60.0)
    d_alt = PulseDiagnostics(signal="LONG", price_pct=0.3, burst=2.5, imbalance_pct=40.0)
    r_weth = PoolEpochResult(pool=weth_pool, added=1, price=3000.0, diag=d_weth, signal="LONG")
    r_alt = PoolEpochResult(pool=alt_pool, added=1, price=15.0, diag=d_alt, signal="LONG")
    best = MultiPoolTracker.pick_best_long([r_weth, r_alt], th)
    assert best is not None
    assert best.pool.label == "USDC/LINK"


def test_tracker_ingest_snapshot() -> None:
    from bds_agent.active_markets import WatchedPool

    now = int(time.time())
    pool = WatchedPool(
        "0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640",
        USDC_ADDRESS,
        "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        1,
        "USDC/WETH",
    )
    tracker = MultiPoolTracker([pool])
    snap = {
        "tradeData": {
            pool.address: {
                "trades": [
                    {
                        "tradeType": "Swap",
                        "data": {
                            "block_timestamp": now,
                            "calculated_trade_amount_usd": 1000.0,
                            "calculated_token0_amount": 1000.0,
                            "calculated_token1_amount": 0.5,
                            "amount0": -1000.0,
                            "amount1": 0.5,
                        },
                        "log": {"transactionHash": "0xabc", "logIndex": 0},
                    },
                ],
            },
        },
    }
    results = tracker.ingest_snapshot(1, snap, PulseThresholds(min_trades=1, cooldown_seconds=0))
    assert len(results) == 1
    assert results[0].added == 1
