"""active_markets request params."""

from __future__ import annotations

from bds_agent.active_markets import fetch_daily_active_pools


def test_daily_active_pools_clamps_size_to_api_max(monkeypatch) -> None:
    captured: dict = {}

    class FakeResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"active_pools": []}

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def get(self, url, headers=None, params=None):
            captured["params"] = params
            return FakeResp()

    monkeypatch.setattr("bds_agent.active_markets.httpx.Client", FakeClient)
    fetch_daily_active_pools("https://bds.example", "sk_test", size=200)
    assert captured["params"]["size"] == 100
