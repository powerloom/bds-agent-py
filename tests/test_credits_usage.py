from __future__ import annotations

from unittest.mock import patch

import httpx

from bds_agent.credits_api import (
    credits_usage,
    credits_usage_by_endpoint,
    credits_usage_summary,
)


def _patch_client(handler):
    transport = httpx.MockTransport(handler)
    inner = httpx.Client(transport=transport, timeout=30.0)

    class _CM:
        def __enter__(self) -> httpx.Client:
            return inner

        def __exit__(self, *args: object) -> None:
            inner.close()

    return patch("bds_agent.credits_api.httpx.Client", lambda **kw: _CM())


def test_credits_usage_requests_ledger_with_limit() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json={
                "org_id": "org_1",
                "transactions": [
                    {
                        "amount": -1,
                        "type": "usage",
                        "route_template": "/mpp/data/{project_id}",
                        "http_method": "GET",
                        "request_path": "/mpp/data/bds-uniswap-v3",
                        "client_source": "cli",
                        "created_at": "2026-05-22T12:00:00Z",
                    }
                ],
            },
        )

    with _patch_client(handler):
        data = credits_usage("https://meter.example", "sk_live_test", limit=25)

    assert seen["path"] == "/credits/usage"
    assert seen["params"] == {"limit": "25"}
    assert seen["auth"] == "Bearer sk_live_test"
    assert data["transactions"][0]["client_source"] == "cli"


def test_credits_usage_summary_requests_window() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={
                "window_days": 14,
                "totals": {"usage_events": 2, "credits_used": 2, "credits_added": 0},
                "by_endpoint": [],
                "by_day": [],
            },
        )

    with _patch_client(handler):
        data = credits_usage_summary("https://meter.example", "sk_live_test", days=14)

    assert seen["path"] == "/credits/usage/summary"
    assert seen["params"] == {"days": "14"}
    assert data["window_days"] == 14


def test_credits_usage_by_endpoint_requests_window_and_limit() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={
                "window_days": 30,
                "by_endpoint": [
                    {
                        "route_template": "/mpp/stream/{project_id}",
                        "http_method": "GET",
                        "call_count": 3,
                        "credits_used": 3,
                    }
                ],
            },
        )

    with _patch_client(handler):
        data = credits_usage_by_endpoint(
            "https://meter.example",
            "sk_live_test",
            days=30,
            limit=10,
        )

    assert seen["path"] == "/credits/usage/by-endpoint"
    assert seen["params"] == {"days": "30", "limit": "10"}
    assert data["by_endpoint"][0]["route_template"] == "/mpp/stream/{project_id}"
