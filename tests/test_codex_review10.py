"""Codex PR #1 review round 10 (2026-05-31 ~15:01 UTC)."""

from __future__ import annotations

import time

import pytest

from bds_agent.pulse import PulseBuffer
from bds_agent.usd_prices import fetch_token_usd_in_pool


def test_current_price_uses_latest_trade_not_median() -> None:
    buf = PulseBuffer(pool_address="0xpool")
    now = int(time.time())
    buf.ingest_epoch_trades(
        1,
        [
            {
                "tradeType": "Swap",
                "data": {
                    "block_timestamp": now - 200,
                    "calculated_trade_amount_usd": 1000.0,
                    "calculated_token0_amount": 1.0,
                    "calculated_token1_amount": 1.0,
                    "amount0": 1.0,
                    "amount1": -1.0,
                },
                "log": {"transactionHash": "old", "logIndex": 0},
            },
            {
                "tradeType": "Swap",
                "data": {
                    "block_timestamp": now - 10,
                    "calculated_trade_amount_usd": 1000.0,
                    "calculated_token0_amount": 1.0,
                    "calculated_token1_amount": 1.0,
                    "amount0": 1.0,
                    "amount1": -1.0,
                },
                "log": {"transactionHash": "new", "logIndex": 0},
            },
        ],
        now_ts=now,
    )
    # Prices implied from amounts — force explicit prices on normalized trades
    for i, px in enumerate((3000.0, 3100.0)):
        buf.trades[i].price = px
        buf.trades[i].ts = now - 200 + i * 190
    assert buf.current_price() == 3100.0


def test_fetch_token_usd_raises_on_402(monkeypatch) -> None:
    class FakeResp:
        status_code = 402
        text = "payment required"

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def get(self, url, headers=None):
            return FakeResp()

    monkeypatch.setattr("bds_agent.usd_prices.httpx.Client", FakeClient)
    with pytest.raises(RuntimeError, match="402"):
        fetch_token_usd_in_pool(
            "https://bds.example/api",
            "sk",
            "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
            "0xE0554a476A092703abdB3Ef35c80e0D76d32939F",
        )
