"""Guard → trader.json / trades log sync."""

from __future__ import annotations

from bds_agent import paths
from bds_agent.active_markets import WatchedPool
from bds_agent.guard_trade_sync import record_guard_fill
from bds_agent.positions import normalize_trader_state, open_positions
from bds_agent.trader_state import load_trader_state, load_trades


def _weth_pool() -> WatchedPool:
    return WatchedPool(
        address="0xe0554a476a092703abdb3ef35c80e0d76d32939f",
        label="USDC/WETH",
        token0="0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        token1="0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
        base_idx=1,
        fee=500,
        base_decimals=18,
        quote_decimals=6,
    )


def test_guard_take_profit_updates_trader_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path)
    pool = _weth_pool()
    guard_state = {"reference_entry_usd": 2000.0, "last_exit_usd": None}
    record_guard_fill(
        profile="g1",
        pool=pool,
        size_usd=25.0,
        dry_run=True,
        guard_state=guard_state,
        action="initial_entry_buy",
        result={
            "action": "initial_entry_buy",
            "dry_run": True,
            "size_usd": 25.0,
            "price_usd": 2000.0,
            "new_position": "token",
        },
        price=2000.0,
    )
    state = normalize_trader_state(load_trader_state("g1"))
    assert len(open_positions(state)) == 1

    record_guard_fill(
        profile="g1",
        pool=pool,
        size_usd=25.0,
        dry_run=True,
        guard_state=guard_state,
        action="take_profit_sell",
        result={
            "action": "take_profit_sell",
            "dry_run": True,
            "tx_hash": "0xabc",
            "new_position": "reserve",
        },
        price=2060.0,
    )
    state = normalize_trader_state(load_trader_state("g1"))
    assert open_positions(state) == []
    trades = load_trades("g1")
    assert len(trades) == 2
    assert trades[-1]["type"] == "EXIT"
    assert trades[-1]["reason"] == "take_profit_sell"
    assert trades[-1]["pnl_usd"] > 0


def test_guard_dry_run_exit_keeps_live_trader_position(tmp_path, monkeypatch) -> None:
    from bds_agent.trader_state import save_trader_state

    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path)
    pool = _weth_pool()
    live_pos = {
        "entry_pool": pool.address,
        "entry_label": pool.label,
        "entry_token": pool.base_token,
        "entry_token0": pool.token0,
        "entry_token1": pool.token1,
        "entry_base_idx": pool.base_idx,
        "entry_fee": pool.fee,
        "entry_base_decimals": pool.base_decimals,
        "entry_price": 2000.0,
        "size_usd": 25.0,
        "entry_tx": "0xlive",
        "dry_run": False,
    }
    save_trader_state({"positions": [live_pos]}, "g2")
    record_guard_fill(
        profile="g2",
        pool=pool,
        size_usd=25.0,
        dry_run=True,
        guard_state={"reference_entry_usd": 2000.0, "last_exit_usd": 2060.0},
        action="take_profit_sell",
        result={"action": "take_profit_sell", "dry_run": True, "new_position": "reserve"},
        price=2060.0,
    )
    state = normalize_trader_state(load_trader_state("g2"))
    assert len(open_positions(state)) == 1
