"""Codex review 3 (f468ff1): reserve startup, dry-run actions, re-entry price sync."""

from __future__ import annotations

from bds_agent import paths
from bds_agent.active_markets import WatchedPool
from bds_agent.guard import GuardConfig, _execute_action, run_initial_entry_if_needed
from bds_agent.guard_trade_sync import record_guard_fill
from bds_agent.positions import normalize_trader_state, open_positions
from bds_agent.trade import TraderConfig, _execute_exit
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


def test_run_initial_entry_skips_when_position_reserve() -> None:
    cfg = GuardConfig(threshold_high=2100.0, threshold_low=2000.0, enter=True)
    pool = _weth_pool()
    pos, result = run_initial_entry_if_needed(
        cfg,
        pool,
        position="reserve",
        price=2050.0,
        rpc_url="http://localhost:8545",
        private_key="0x" + "11" * 32,
        chain_id=1,
    )
    assert pos == "reserve"
    assert result is not None
    assert result.get("skipped") is True
    assert "reserve" in str(result.get("reason", "")).lower()


def test_dry_run_execute_action_sets_new_position() -> None:
    cfg = GuardConfig(threshold_high=1.0, threshold_low=0.5, dry_run=True)
    pool = _weth_pool()
    sell = _execute_action(
        cfg,
        pool,
        "take_profit_sell",
        1.05,
        rpc_url="",
        private_key="",
        chain_id=1,
    )
    assert sell["new_position"] == "reserve"
    buy = _execute_action(
        cfg,
        pool,
        "reentry_buy_dip",
        0.95,
        rpc_url="",
        private_key="",
        chain_id=1,
    )
    assert buy["new_position"] == "token"


def test_reentry_fill_uses_current_price_not_stale_reference(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path)
    pool = _weth_pool()
    guard_state = {"reference_entry_usd": 2000.0, "last_exit_usd": 2060.0}
    record_guard_fill(
        profile="g3",
        pool=pool,
        size_usd=25.0,
        dry_run=True,
        guard_state=guard_state,
        action="reentry_buy_dip",
        result={
            "action": "reentry_buy_dip",
            "dry_run": True,
            "price_usd": 2045.0,
            "size_usd": 25.0,
            "new_position": "token",
        },
        price=2045.0,
    )
    state = normalize_trader_state(load_trader_state("g3"))
    positions = open_positions(state)
    assert len(positions) == 1
    assert positions[0]["entry_price"] == 2045.0


def test_dry_run_exit_does_not_clear_live_position(tmp_path, monkeypatch) -> None:
    from rich.console import Console

    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path)
    pool_addr = "0xe0554a476a092703abdb3ef35c80e0d76d32939f"
    state = {
        "positions": [
            {
                "entry_pool": pool_addr,
                "entry_label": "USDC/WETH",
                "entry_token": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
                "entry_token0": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
                "entry_token1": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
                "entry_base_idx": 1,
                "entry_fee": 500,
                "entry_base_decimals": 18,
                "entry_price": 2000.0,
                "size_usd": 25.0,
                "entry_tx": "0xlive",
                "dry_run": False,
            },
        ],
    }
    cfg = TraderConfig(dry_run=True, profile="live-exit")
    out = Console(highlight=False)
    pos = state["positions"][0]
    updated = _execute_exit(
        cfg,
        state,
        pos,
        epoch_i=1,
        exit_price=2100.0,
        reason="manual",
        out=out,
    )
    assert len(open_positions(updated)) == 1
    trades = load_trades("live-exit")
    assert trades[-1]["type"] == "EXIT"
    assert trades[-1]["dry_run"] is True
