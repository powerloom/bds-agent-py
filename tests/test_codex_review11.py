"""Codex PR #1 review round 11 (2026-06-01)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bds_agent.guard import GuardConfig, run_initial_entry_if_needed
from bds_agent.guard_state import guard_state_path
from bds_agent.paths import profiles_dir


def test_guard_state_path_blocks_path_traversal() -> None:
    with pytest.raises(ValueError, match="Profile name"):
        guard_state_path("../evil")


def test_guard_state_path_stays_in_profiles_dir() -> None:
    p = guard_state_path("my-team")
    assert p.parent.resolve() == profiles_dir().resolve()
    assert p.name == "my-team.guard.json"


def test_run_initial_entry_allows_usdc_below_size(monkeypatch) -> None:
    from bds_agent.active_markets import WatchedPool

    pool = WatchedPool(
        "0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640",
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        1,
        "USDC/WETH",
        fee=500,
    )
    cfg = GuardConfig(enter=True, size_usd=25.0, dry_run=False)
    monkeypatch.setattr(
        "bds_agent.evm_tx.wait_for_no_pending_txs",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "bds_agent.guard.get_erc20_balance_human",
        lambda _rpc, token, *_a, **_k: 0.0 if "c02" in str(token).lower() else 24.0,
    )
    monkeypatch.setattr(
        "eth_account.Account.from_key",
        lambda _k: MagicMock(address="0x" + "22" * 20),
    )
    monkeypatch.setattr("bds_agent.evm_swap._web3", lambda _url: MagicMock())
    monkeypatch.setattr(
        "bds_agent.guard.execute_initial_entry",
        lambda *_a, **_k: {"new_position": "token", "tx": "0xabc", "size_usd": 24.0},
    )
    pos, result = run_initial_entry_if_needed(
        cfg,
        pool,
        position="reserve",
        price=3000.0,
        rpc_url="http://x",
        private_key="0x" + "11" * 32,
        chain_id=1,
        allow_reserve_enter=True,
    )
    assert pos == "token"
    assert result.get("tx") == "0xabc"


def test_trade_resolve_api_key_uses_named_profile(tmp_path, monkeypatch) -> None:
    prof = tmp_path / "profiles"
    prof.mkdir()
    (prof / "team-a.json").write_text(
        '{"api_key": "sk_live_team_a_key_xxxxxxxx"}',
        encoding="utf-8",
    )
    monkeypatch.setattr("bds_agent.paths.profiles_dir", lambda: prof)
    monkeypatch.setattr(
        "bds_agent.prices_cmd.profiles_dir",
        lambda: prof,
    )
    from bds_agent.trade import _resolve_api_key

    assert _resolve_api_key("team-a") == "sk_live_team_a_key_xxxxxxxx"
