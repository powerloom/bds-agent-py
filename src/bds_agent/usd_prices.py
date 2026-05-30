"""BDS USD price feed — pool-scoped and all-pools routes under /mpp/."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from bds_agent.client import CLIENT_SOURCE_CLI, CLIENT_SOURCE_HEADER
import httpx
from web3 import Web3

_RETRYABLE_HTTP = frozenset({429, 502, 503, 504})
_DEFAULT_MAX_ATTEMPTS = 5


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        CLIENT_SOURCE_HEADER: CLIENT_SOURCE_CLI,
    }


def _token_price_in_pool_url(
    base_url: str,
    token_address: str,
    pool_address: str,
    block_number: int | None = None,
) -> str:
    token = Web3.to_checksum_address(token_address)
    pool = Web3.to_checksum_address(pool_address)
    root = base_url.rstrip("/")
    if block_number is None:
        return f"{root}/mpp/token/price/{token}/{pool}"
    return f"{root}/mpp/token/price/{token}/{pool}/{int(block_number)}"


def _token_prices_all_url(
    base_url: str,
    token_address: str,
    block_number: int | None = None,
) -> str:
    token = Web3.to_checksum_address(token_address)
    root = base_url.rstrip("/")
    if block_number is None:
        return f"{root}/mpp/tokenPrices/all/{token}"
    return f"{root}/mpp/tokenPrices/all/{token}/{int(block_number)}"


def _parse_price_scalar(body: Any) -> float | None:
    if isinstance(body, (int, float)):
        price = float(body)
        return price if price > 0 else None
    if not isinstance(body, dict):
        return None
    if body.get("error"):
        return None
    for key in ("price", "price_usd", "usd_price", "value"):
        val = body.get(key)
        if val is None:
            continue
        try:
            price = float(val)
        except (TypeError, ValueError):
            continue
        return price if price > 0 else None
    return None


def _retry_sleep_seconds(
    *,
    attempt: int,
    resp: httpx.Response | None = None,
) -> float:
    if resp is not None:
        raw = resp.headers.get("Retry-After")
        if raw is not None:
            try:
                return max(1.0, min(float(raw), 60.0))
            except ValueError:
                pass
    return min(60.0, 2.0**attempt)


def _http_get_with_retry(
    url: str,
    *,
    headers: dict[str, str],
    timeout: float,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    on_retry: Callable[[int, str], None] | None = None,
) -> httpx.Response:
    """GET with backoff on transient origin/gateway errors and network faults."""
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(url, headers=headers)
        except httpx.RequestError as exc:
            last_error = exc
            if attempt + 1 >= max_attempts:
                raise RuntimeError(f"BDS request failed for {url}: {exc}") from exc
            reason = f"network: {exc}"
            if on_retry is not None:
                on_retry(attempt + 1, reason)
            time.sleep(_retry_sleep_seconds(attempt=attempt))
            continue
        if resp.status_code in _RETRYABLE_HTTP:
            if attempt + 1 >= max_attempts:
                detail = (resp.text or "")[:300]
                raise RuntimeError(
                    f"BDS price HTTP {resp.status_code} for {url}: {detail}",
                )
            reason = f"HTTP {resp.status_code}"
            if on_retry is not None:
                on_retry(attempt + 1, reason)
            time.sleep(_retry_sleep_seconds(attempt=attempt, resp=resp))
            continue
        return resp
    if last_error is not None:
        raise RuntimeError(f"BDS request failed for {url}: {last_error}") from last_error
    raise RuntimeError(f"BDS request failed for {url}: exhausted {max_attempts} attempts")


def _parse_price_map(body: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, val in body.items():
        if val is None:
            continue
        try:
            price = float(val)
        except (TypeError, ValueError):
            continue
        if price > 0:
            out[str(key).lower()] = price
    return out


def fetch_token_usd_in_pool(
    base_url: str,
    api_key: str,
    token_address: str,
    pool_address: str,
    block_number: int | None = None,
    *,
    timeout: float = 30.0,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    on_retry: Callable[[int, str], None] | None = None,
) -> float | None:
    """
    GET /mpp/token/price/{token}/{pool}[/{block}] — one pool, one scalar USD price.

    Mirrors the public ``GET /token/price/...`` route and hosted MCP tool
    ``bds_mpp_token_price_token_address_pool_address``. When ``block_number`` is omitted,
    BDS resolves the snapshotter's latest epoch for that pool (not RPC chain head).

    Returns USD price of ``token_address`` in that pool, or None.
    """
    url = _token_price_in_pool_url(
        base_url,
        token_address,
        pool_address,
        block_number,
    )
    resp = _http_get_with_retry(
        url,
        headers=_headers(api_key),
        timeout=timeout,
        max_attempts=max_attempts,
        on_retry=on_retry,
    )
    if resp.status_code in (404, 402):
        return None
    if resp.status_code >= 400:
        detail = (resp.text or "")[:300]
        raise RuntimeError(
            f"BDS price HTTP {resp.status_code} for {url}: {detail}",
        )
    try:
        body = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"BDS price response is not JSON for {url}") from exc
    return _parse_price_scalar(body)


def fetch_token_usd_at_pool(
    base_url: str,
    api_key: str,
    token_address: str,
    pool_address: str,
    block_number: int | None = None,
    *,
    timeout: float = 30.0,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    on_retry: Callable[[int, str], None] | None = None,
) -> float | None:
    """Alias for :func:`fetch_token_usd_in_pool` (preferred pool-scoped route)."""
    return fetch_token_usd_in_pool(
        base_url,
        api_key,
        token_address,
        pool_address,
        block_number,
        timeout=timeout,
        max_attempts=max_attempts,
        on_retry=on_retry,
    )


def fetch_all_token_prices(
    base_url: str,
    api_key: str,
    token_address: str,
    block_number: int | None = None,
    *,
    timeout: float = 30.0,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    on_retry: Callable[[int, str], None] | None = None,
) -> dict[str, float]:
    """
    GET /mpp/tokenPrices/all/{token}[/{block}] → ``{pool_address_lower: usd_price}``.
    """
    url = _token_prices_all_url(base_url, token_address, block_number)
    resp = _http_get_with_retry(
        url,
        headers=_headers(api_key),
        timeout=timeout,
        max_attempts=max_attempts,
        on_retry=on_retry,
    )
    if resp.status_code == 404:
        return {}
    if resp.status_code >= 400:
        detail = (resp.text or "")[:300]
        raise RuntimeError(
            f"BDS tokenPrices HTTP {resp.status_code} for {url}: {detail}",
        )
    try:
        body = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"BDS tokenPrices response is not JSON for {url}") from exc
    if not isinstance(body, dict):
        return {}
    return _parse_price_map(body)


def _price_from_map(body: dict[str, Any], pool_key: str) -> float | None:
    for key, val in body.items():
        if str(key).lower() != pool_key:
            continue
        if val is None:
            return None
        try:
            price = float(val)
        except (TypeError, ValueError):
            return None
        return price if price > 0 else None
    return None
