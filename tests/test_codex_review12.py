"""Codex PR #1 review round 12 (2026-06-02)."""

from __future__ import annotations

from bds_agent import paths
from bds_agent.active_markets import WatchedPool
from bds_agent.guard_trade_sync import _record_guard_entry, _record_guard_exit
from bds_agent.positions import is_paper_position, normalize_trader_state, open_positions, position_sell_tokens
from bds_agent.trader_state import load_trader_state, save_trader_state


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


def test_position_sell_tokens_caps_to_recorded() -> None:
    pos = {"token_balance": 0.01, "size_usd": 25.0}
    assert position_sell_tokens(pos, 1.0) == 0.01


def test_live_guard_entry_replaces_paper_position(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path)
    pool = _weth_pool()
    paper = {
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
        "entry_tx": "dry-run",
        "dry_run": True,
    }
    save_trader_state({"positions": [paper]}, "g-paper")
    _record_guard_entry(
        profile="g-paper",
        pool=pool,
        size_usd=24.0,
        dry_run=False,
        guard_state={"reference_entry_usd": 2000.0},
        action="initial_entry_buy",
        result={
            "action": "initial_entry_buy",
            "tx_hash": "0xlive",
            "size_usd": 24.0,
            "price_usd": 2000.0,
        },
        price=2000.0,
        rpc_url=None,
        private_key=None,
    )
    state = normalize_trader_state(load_trader_state("g-paper"))
    assert len(open_positions(state)) == 1
    pos = open_positions(state)[0]
    assert not is_paper_position(pos)
    assert pos.get("entry_tx") == "0xlive"
    assert float(pos.get("token_balance") or 0) > 0


def test_guard_entry_persisted_when_balance_read_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path)
    pool = _weth_pool()

    def _boom(*_a, **_k):
        raise RuntimeError("RPC timeout")

    monkeypatch.setattr(
        "bds_agent.guard_trade_sync.get_erc20_balance_human",
        _boom,
    )
    _record_guard_entry(
        profile="g-rpc",
        pool=pool,
        size_usd=25.0,
        dry_run=False,
        guard_state={"reference_entry_usd": 2000.0},
        action="initial_entry_buy",
        result={
            "action": "initial_entry_buy",
            "tx_hash": "0xabc",
            "size_usd": 25.0,
            "price_usd": 2000.0,
        },
        price=2000.0,
        rpc_url="http://x",
        private_key="0x" + "11" * 32,
    )
    state = normalize_trader_state(load_trader_state("g-rpc"))
    assert len(open_positions(state)) == 1
    assert open_positions(state)[0].get("entry_tx") == "0xabc"


def test_guard_exit_removes_position_when_balance_read_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path)
    pool = _weth_pool()
    live = {
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
        "token_balance": 0.01,
        "dry_run": False,
    }
    save_trader_state({"positions": [live]}, "g-exit")
    monkeypatch.setattr(
        "bds_agent.guard_trade_sync._refresh_balances",
        lambda s, **_k: (_ for _ in ()).throw(RuntimeError("RPC")),
    )
    _record_guard_exit(
        profile="g-exit",
        pool=pool,
        size_usd=25.0,
        dry_run=False,
        guard_state={"reference_entry_usd": 2000.0, "last_exit_usd": 2060.0},
        action="take_profit_sell",
        result={"action": "take_profit_sell", "tx_hash": "0xsell"},
        price=2060.0,
        rpc_url="http://x",
        private_key="0x" + "11" * 32,
    )
    state = normalize_trader_state(load_trader_state("g-exit"))
    assert open_positions(state) == []
