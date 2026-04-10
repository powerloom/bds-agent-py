"""
Bearer-authenticated HTTP client for the snapshotter full node HTTP API (resolver + compute routes).

Uses the API key from ``bds-agent`` profiles (``Authorization: Bearer``).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

CREDIT_BALANCE_HEADER = "X-BDS-Credit-Balance"


@dataclass(frozen=True)
class StreamChunk:
    """One SSE ``data:`` JSON object plus credit balance from the HTTP response headers."""

    data: dict[str, Any]
    credit_balance: int | None


@dataclass(frozen=True)
class FetchResult:
    """JSON body of a successful GET plus status and metering header."""

    data: dict[str, Any]
    status_code: int
    credit_balance: int | None


class BdsClientError(Exception):
    """HTTP error or invalid JSON from BDS API."""


def _credit_balance_from_headers(headers: httpx.Headers) -> int | None:
    raw = headers.get(CREDIT_BALANCE_HEADER)
    if raw is None or raw == "":
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


def _bearer_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _join_url(base_url: str, endpoint: str, query: dict[str, Any] | None) -> str:
    path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    url = base_url.rstrip("/") + path
    if query:
        q = {k: v for k, v in query.items() if v is not None}
        if q:
            url = f"{url}?{urlencode({k: str(v) for k, v in q.items()})}"
    return url


async def _iter_sse_data_lines(
    response: httpx.Response,
    *,
    max_events: int = 0,
) -> AsyncIterator[dict[str, Any]]:
    """Yield each JSON object from SSE ``data:`` lines."""
    n = 0
    async for line in response.aiter_lines():
        if not line:
            continue
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        yield obj
        if "epoch" in obj:
            n += 1
        if max_events and n >= max_events:
            break


async def stream(
    base_url: str,
    endpoint: str,
    api_key: str,
    *,
    from_epoch: int | None = None,
    query_params: dict[str, Any] | None = None,
    reconnect_delay: float = 5.0,
    max_reconnects: int = 0,
    max_events: int = 0,
    reconnect: bool = True,
    connect_timeout: float = 60.0,
) -> AsyncIterator[StreamChunk]:
    """
    SSE stream: reconnects on failure (and after a clean server close if ``reconnect`` is True).

    ``from_epoch`` is merged into the query string (for ``/mpp/stream/allTrades``).

    ``max_reconnects``: ``0`` means unlimited reconnect attempts after errors. The counter resets
    after a connection completes normally (server closed the SSE body). Sleeps only after errors;
    immediate reconnect when the server closes the stream cleanly.

    Yields :class:`StreamChunk` with ``credit_balance`` from the **opening** response headers
    (``X-BDS-Credit-Balance``) for that connection.
    """
    qp: dict[str, Any] = dict(query_params) if query_params else {}
    if from_epoch is not None:
        qp["from_epoch"] = from_epoch

    failures = 0
    while True:
        try:
            async for chunk in _stream_single_connection(
                base_url,
                endpoint,
                api_key,
                query_params=qp,
                max_events=max_events,
                connect_timeout=connect_timeout,
            ):
                yield chunk
            # Server closed the SSE body successfully.
            failures = 0
            if not reconnect:
                break
            continue
        except asyncio.CancelledError:
            raise
        except Exception:
            if not reconnect:
                raise
            failures += 1
            if max_reconnects and failures >= max_reconnects:
                raise
            await asyncio.sleep(reconnect_delay)


async def _stream_single_connection(
    base_url: str,
    endpoint: str,
    api_key: str,
    *,
    query_params: dict[str, Any] | None,
    max_events: int,
    connect_timeout: float,
) -> AsyncIterator[StreamChunk]:
    url = _join_url(base_url, endpoint, query_params)
    timeout = httpx.Timeout(None, connect=connect_timeout)
    headers = {
        **_bearer_headers(api_key),
        "Accept": "text/event-stream",
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("GET", url, headers=headers) as response:
            credit = _credit_balance_from_headers(response.headers)
            if response.status_code != 200:
                body = await response.aread()
                msg = body.decode(errors="replace")[:2048]
                raise BdsClientError(
                    f"SSE failed HTTP {response.status_code}: {msg}",
                )

            async for obj in _iter_sse_data_lines(response, max_events=max_events):
                yield StreamChunk(data=obj, credit_balance=credit)


async def fetch(
    base_url: str,
    endpoint: str,
    api_key: str,
    **params: Any,
) -> FetchResult:
    """
    Single GET with Bearer auth. ``params`` become **query string** parameters.

    Example: ``fetch(base, "/mpp/snapshot/allTrades/24785718", key)``
    or ``fetch(base, "/mpp/snapshot/allTrades", key)`` for latest.

    Raises :exc:`BdsClientError` on non-2xx or non-JSON response.
    """
    url = _join_url(base_url, endpoint, params or None)
    headers = _bearer_headers(api_key)
    timeout = httpx.Timeout(120.0, connect=60.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url, headers=headers)

    credit = _credit_balance_from_headers(response.headers)
    if response.status_code == 402:
        raise BdsClientError(
            f"HTTP 402 Payment Required — credits exhausted or billing failed "
            f"(X-BDS-Credit-Balance={credit!r})",
        )
    if response.status_code < 200 or response.status_code >= 300:
        text = response.text[:2048]
        raise BdsClientError(f"HTTP {response.status_code}: {text}")

    try:
        data = response.json()
    except json.JSONDecodeError as e:
        raise BdsClientError(f"Response is not JSON: {e}") from e
    if not isinstance(data, dict):
        raise BdsClientError("JSON root must be an object")

    return FetchResult(data=data, status_code=response.status_code, credit_balance=credit)
