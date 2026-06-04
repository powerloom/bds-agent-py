"""BDS daily active pools/tokens — watchlist for multi-pool Pulse."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bds_agent.client import CLIENT_SOURCE_CLI, CLIENT_SOURCE_HEADER
import httpx
from web3 import Web3

from bds_agent.evm_swap import USDC

USDC_ADDRESS = Web3.to_checksum_address(USDC)


@dataclass(frozen=True)
class WatchedPool:
    """USDC-quoted Uniswap V3 pool eligible for Pulse + USDC↔token swaps."""

    address: str
    token0: str
    token1: str
    base_idx: int
    label: str
    frequency: int = 0
    fee: int = 0
    base_decimals: int = 18
    quote_decimals: int = 6

    @property
    def base_token(self) -> str:
        return self.token0 if self.base_idx == 0 else self.token1

    @property
    def usdc_token(self) -> str:
        return self.token1 if self.base_idx == 0 else self.token0

    def live_swap_ready(self) -> bool:
        """True when pool has enough metadata for Uniswap V3 exactInputSingle."""
        return bool(self.address and self.fee > 0 and self.base_decimals > 0)


def _parse_metadata(entry: dict[str, Any]) -> dict[str, Any] | None:
    meta = entry.get("metadata")
    if not isinstance(meta, dict):
        return None
    return meta


def watched_pool_from_entry(entry: dict[str, Any]) -> WatchedPool | None:
    """Build WatchedPool from dailyActivePools row (metadata=true)."""
    pool_raw = entry.get("pool_address")
    if not isinstance(pool_raw, str) or not pool_raw.startswith("0x"):
        return None
    meta = _parse_metadata(entry)
    if not meta:
        return None
    t0 = meta.get("token0") or {}
    t1 = meta.get("token1") or {}
    if not isinstance(t0, dict) or not isinstance(t1, dict):
        return None
    a0 = t0.get("address")
    a1 = t1.get("address")
    if not isinstance(a0, str) or not isinstance(a1, str):
        return None
    token0 = Web3.to_checksum_address(a0)
    token1 = Web3.to_checksum_address(a1)
    s0 = str(t0.get("symbol") or token0[:8])
    s1 = str(t1.get("symbol") or token1[:8])
    freq = int(entry.get("frequency") or 0)

    if token0 == USDC_ADDRESS and token1 != USDC_ADDRESS:
        base_idx = 1
    elif token1 == USDC_ADDRESS and token0 != USDC_ADDRESS:
        base_idx = 0
    else:
        return None

    base_meta = t0 if base_idx == 0 else t1
    raw_fee = meta.get("fee")
    if raw_fee is None:
        fee = 0
    else:
        try:
            fee = int(raw_fee)
        except (TypeError, ValueError):
            fee = 0
    try:
        base_decimals = int(base_meta.get("decimals") or 18)
    except (TypeError, ValueError):
        base_decimals = 18

    return WatchedPool(
        address=Web3.to_checksum_address(pool_raw),
        token0=token0,
        token1=token1,
        base_idx=base_idx,
        label=f"{s0}/{s1}",
        frequency=freq,
        fee=fee,
        base_decimals=base_decimals,
    )


def fetch_watched_pool(
    base_url: str,
    api_key: str,
    pool_address: str,
    *,
    timeout: float = 60.0,
) -> WatchedPool | None:
    """
    Resolve one USDC-quoted pool for guard/trade.

    Tries ``GET /mpp/pool/{address}/metadata`` first, then scans dailyActivePools (size ≤ 100).
    """
    addr = Web3.to_checksum_address(pool_address)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        CLIENT_SOURCE_HEADER: CLIENT_SOURCE_CLI,
    }
    meta_url = f"{base_url.rstrip('/')}/mpp/pool/{addr}/metadata"
    with httpx.Client(timeout=timeout) as client:
        resp = client.get(meta_url, headers=headers)
        if resp.status_code == 200:
            body = resp.json()
            if isinstance(body, dict) and not body.get("error"):
                wp = watched_pool_from_entry(
                    {"pool_address": addr, "metadata": body, "frequency": 0},
                )
                if wp is not None:
                    return wp
    pools = fetch_daily_active_pools(
        base_url,
        api_key,
        time_interval=300,
        size=100,
        metadata=True,
        timeout=timeout,
    )
    key = addr.lower()
    for wp in pools:
        if wp.address.lower() == key:
            return wp
    return None


def fetch_daily_active_pools(
    base_url: str,
    api_key: str,
    *,
    time_interval: int = 300,
    size: int = 50,
    metadata: bool = True,
    timeout: float = 60.0,
) -> list[WatchedPool]:
    """GET /mpp/dailyActivePools — USDC-quoted pools only, sorted by frequency."""
    size = max(1, min(int(size), 100))
    url = f"{base_url.rstrip('/')}/mpp/dailyActivePools"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        CLIENT_SOURCE_HEADER: CLIENT_SOURCE_CLI,
    }
    params: dict[str, Any] = {
        "page": 1,
        "size": size,
        "metadata": metadata,
        "time_interval": time_interval,
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        body = resp.json()
    rows = body.get("active_pools") or []
    if not isinstance(rows, list):
        return []
    by_addr: dict[str, WatchedPool] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        wp = watched_pool_from_entry(row)
        if wp is None:
            continue
        key = wp.address.lower()
        prev = by_addr.get(key)
        if prev is None or wp.frequency > prev.frequency:
            by_addr[key] = wp
    out = sorted(by_addr.values(), key=lambda p: p.frequency, reverse=True)
    return out
