"""USD price feed client tests."""

from __future__ import annotations

import pytest

from bds_agent.usd_prices import (
    _parse_price_scalar,
    _price_from_map,
    fetch_token_usd_in_pool,
)


def test_price_from_map_case_insensitive() -> None:
    body = {
        "0xAbC": 1.23,
        "0xOther": 9.99,
    }
    assert _price_from_map(body, "0xabc") == 1.23


def test_price_from_map_missing() -> None:
    assert _price_from_map({"0xabc": 1.0}, "0xdef") is None


def test_parse_price_scalar_float() -> None:
    assert _parse_price_scalar(2003.29) == 2003.29
    assert _parse_price_scalar(0) is None
    assert _parse_price_scalar({"error": "not found"}) is None


def test_fetch_token_usd_in_pool(monkeypatch) -> None:
    class FakeResp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> float:
            return 2003.2998465631588

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def get(self, url, headers=None):
            assert "/mpp/token/price/0xC02a" in url
            assert "0xE055" in url
            assert headers and headers.get("Authorization", "").startswith("Bearer ")
            return FakeResp()

    monkeypatch.setattr("bds_agent.usd_prices.httpx.Client", FakeClient)
    price = fetch_token_usd_in_pool(
        "https://bds.example/api",
        "sk",
        "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "0xE0554a476A092703abdB3Ef35c80e0D76d32939F",
    )
    assert price == 2003.2998465631588


def test_fetch_token_usd_in_pool_auth_error_raises(monkeypatch) -> None:
    class FakeResp:
        status_code = 401
        text = "Unauthorized"

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
    with pytest.raises(RuntimeError, match="HTTP 401"):
        fetch_token_usd_in_pool(
            "https://bds.example/api",
            "bad-key",
            "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
            "0xE0554a476A092703abdB3Ef35c80e0D76d32939F",
        )
