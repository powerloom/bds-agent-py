"""Helpers for Uniswap V3 allTrades snapshot trade dicts."""

from __future__ import annotations

from typing import Any


def norm_pool(addr: str) -> str:
    return addr.strip().lower()


def trade_usd(trade: dict[str, Any]) -> float:
    data = trade.get("data") or {}
    v = data.get("calculated_trade_amount_usd", 0)
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def sqrt_price(trade: dict[str, Any]) -> int | None:
    data = trade.get("data") or {}
    v = data.get("sqrtPriceX96")
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def is_swap(trade: dict[str, Any]) -> bool:
    tt = trade.get("tradeType")
    if tt is None:
        return False
    if isinstance(tt, dict) and "value" in tt:
        return str(tt.get("value")) == "Swap"
    return str(tt) == "Swap"


def epoch_swap_volume_usd(trades: list[dict[str, Any]]) -> float:
    total = 0.0
    for t in trades:
        if isinstance(t, dict) and is_swap(t):
            total += trade_usd(t)
    return total


def token_addresses_in_trade_data(trade: dict[str, Any]) -> set[str]:
    """Lowercased 0x addresses from common Uniswap swap fields in ``trade[''data'']``."""
    out: set[str] = set()
    data = trade.get("data")
    if not isinstance(data, dict):
        return out
    for key in ("token0", "token1", "recipient", "sender"):
        v = data.get(key)
        if isinstance(v, str) and v.startswith("0x"):
            out.add(v.strip().lower())
    return out
