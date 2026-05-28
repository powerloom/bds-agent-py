"""Trade wallet config (`.trade.env`) tests."""

from __future__ import annotations

import os

import pytest

from bds_agent.trade_config import (
    TRADE_CHAIN_ID_ENV,
    TRADE_PRIVATE_KEY_ENV,
    TRADE_RPC_URL_ENV,
    load_trade_env_file,
    resolve_trade_wallet,
    write_trade_env_file,
)


def test_trade_env_roundtrip(tmp_path, monkeypatch) -> None:
    from bds_agent import paths
    from bds_agent.credentials import resolve_trade_env_path

    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path)
    monkeypatch.setenv("BDS_AGENT_PROFILE", "trading")

    p = resolve_trade_env_path()
    assert p is not None
    assert str(p).endswith("trading.trade.env")

    write_trade_env_file(
        "0xabc123",
        rpc_url="https://rpc.example",
        chain_id="1",
        path=p,
    )
    for k in (TRADE_PRIVATE_KEY_ENV, TRADE_RPC_URL_ENV, TRADE_CHAIN_ID_ENV, "EVM_PRIVATE_KEY"):
        monkeypatch.delenv(k, raising=False)

    load_trade_env_file()
    pk, rpc, chain = resolve_trade_wallet()
    assert pk.startswith("0x")
    assert rpc == "https://rpc.example"
    assert chain == 1


def test_trade_wallet_never_reads_billing_evm_env(tmp_path, monkeypatch) -> None:
    from bds_agent import paths

    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path)
    monkeypatch.setenv("BDS_AGENT_PROFILE", "trading")

    billing = tmp_path / "trading.evm.env"
    billing.write_text(
        "EVM_PRIVATE_KEY=0xbilling\nEVM_RPC_URL=https://billing.rpc\nEVM_CHAIN_ID=1\n",
        encoding="utf-8",
    )
    for k in (TRADE_PRIVATE_KEY_ENV, TRADE_RPC_URL_ENV, TRADE_CHAIN_ID_ENV):
        monkeypatch.delenv(k, raising=False)

    with pytest.raises(RuntimeError, match="trade setup-evm"):
        resolve_trade_wallet()
