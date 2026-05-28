"""CLI helpers for ``bds-agent prices`` — reference client for the USD Price Feed."""

from __future__ import annotations

import json
from typing import Any

from bds_agent.credentials import load_credentials
from bds_agent.defaults import DEFAULT_BDS_BASE_URL
from bds_agent.profile_env import resolve_bds_base_url
from bds_agent.usd_prices import fetch_all_token_prices, fetch_token_usd_in_pool
from web3 import Web3


def _resolve_api_key(profile: str | None) -> str:
    """Resolve API key from active profile (set ``--profile`` / ``BDS_AGENT_PROFILE`` before call)."""
    _ = profile  # CLI applies profile via env; load_credentials() reads active profile file
    creds = load_credentials()
    key = (creds or {}).get("api_key")
    if not isinstance(key, str) or not key.strip():
        raise RuntimeError("Invalid or missing api_key in profile credentials.")
    return key.strip()


def _resolve_base_url(profile: str | None) -> str:
    _ = profile
    bu = resolve_bds_base_url()
    return (bu or DEFAULT_BDS_BASE_URL).rstrip("/")


def fetch_pool_price(
    *,
    profile: str | None,
    token: str,
    pool: str,
    block: int | None,
) -> dict[str, Any]:
    api_key = _resolve_api_key(profile)
    base_url = _resolve_base_url(profile)
    token_cs = Web3.to_checksum_address(token)
    pool_cs = Web3.to_checksum_address(pool)
    price = fetch_token_usd_in_pool(
        base_url,
        api_key,
        token_cs,
        pool_cs,
        block,
    )
    return {
        "token": token_cs,
        "pool": pool_cs,
        "block": block,
        "price_usd": price,
    }


def fetch_token_prices(
    *,
    profile: str | None,
    token: str,
    block: int | None,
) -> dict[str, Any]:
    api_key = _resolve_api_key(profile)
    base_url = _resolve_base_url(profile)
    token_cs = Web3.to_checksum_address(token)
    prices = fetch_all_token_prices(base_url, api_key, token_cs, block)
    return {
        "token": token_cs,
        "block": block,
        "pools": prices,
        "pool_count": len(prices),
    }


def format_prices_output(data: dict[str, Any], *, as_json: bool) -> str:
    if as_json:
        return json.dumps(data, indent=2, sort_keys=True)
    if "pools" in data:
        lines = [
            f"token {data['token']}",
            f"block {data.get('block') or 'latest'}",
            f"pools {data.get('pool_count', 0)}",
        ]
        for pool, price in sorted((data.get("pools") or {}).items()):
            lines.append(f"  {pool}  ${price:.8g}")
        return "\n".join(lines)
    price = data.get("price_usd")
    price_s = f"${price:.8g}" if price is not None else "(none)"
    return (
        f"token {data['token']}\n"
        f"pool  {data['pool']}\n"
        f"block {data.get('block') or 'latest'}\n"
        f"price {price_s}"
    )
