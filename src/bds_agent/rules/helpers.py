"""Helpers for Uniswap V3 allTrades snapshot trade dicts."""

from __future__ import annotations

import re
from typing import Any

# Int/float or strings like "50000", "50k", "$50,000", "1.5M" (when suffix allowed).
_NUM_WITH_SUFFIX = re.compile(
    r"^\s*([-+]?(?:\d+\.?\d*|\.\d+))\s*([kKmM])?\s*$",
)


def norm_pool(addr: str) -> str:
    return addr.strip().lower()


def parse_rule_float(value: Any, *, allow_km_suffix: bool = False) -> float:
    """
    Parse a numeric YAML rule field from ``int`` / ``float`` or a string.

    LLMs and humans sometimes write ``50k`` or ``\\$50,000`` for USD thresholds; YAML may also
    mangle abbreviations. When ``allow_km_suffix`` is True, ``k`` / ``m`` multiply the base number.
    """
    if isinstance(value, bool):
        raise ValueError(f"invalid numeric value: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).strip().replace(",", "")
    if not raw:
        raise ValueError("empty numeric value")
    if raw.startswith("$"):
        raw = raw[1:].strip()
    if not raw:
        raise ValueError("empty numeric value")
    if allow_km_suffix:
        m = _NUM_WITH_SUFFIX.match(raw)
        if m:
            n = float(m.group(1))
            suf = (m.group(2) or "").lower()
            if suf == "k":
                n *= 1_000.0
            elif suf == "m":
                n *= 1_000_000.0
            return n
    try:
        return float(raw)
    except ValueError as e:
        raise ValueError(f"not a valid number: {value!r}") from e


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
