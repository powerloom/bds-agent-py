"""Guard startup: credentials and base URL resolution (no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bds_agent.guard import (
    GuardConfig,
    _resolve_watched_pool,
    resolve_guard_base_token,
    resolve_guard_pool_address,
)
from bds_agent.guard_state import default_guard_state
from bds_agent.prices_cmd import _resolve_api_key, _resolve_base_url


def test_resolve_api_key_and_base_url_from_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    profiles = tmp_path / ".config" / "bds-agent" / "profiles"
    profiles.mkdir(parents=True)
    (profiles / "p1.json").write_text(
        json.dumps(
            {
                "api_key": "sk_live_test_key_12345",
                "org_id": "",
                "signup_base_url": "",
                "bds_base_url": "https://bds.example",
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BDS_AGENT_PROFILE", "p1")
    monkeypatch.delenv("BDS_BASE_URL", raising=False)

    assert _resolve_api_key("p1") == "sk_live_test_key_12345"
    assert _resolve_base_url("p1") == "https://bds.example"


def test_resolve_watched_pool_finds_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    from bds_agent.active_markets import WatchedPool

    wp = WatchedPool(
        address="0xE0554a476A092703abdB3Ef35c80e0D76d32939F",
        token0="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        token1="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        base_idx=1,
        label="USDC/WETH",
        fee=500,
        base_decimals=18,
    )

    monkeypatch.setattr(
        "bds_agent.guard._resolve_api_key",
        lambda _p: "sk_live_x",
    )
    monkeypatch.setattr(
        "bds_agent.guard._resolve_base_url",
        lambda _p: "https://bds.example",
    )
    monkeypatch.setattr(
        "bds_agent.guard.fetch_watched_pool",
        lambda *_a, **_k: wp,
    )

    cfg = GuardConfig(
        pool="0xE0554a476A092703abdB3Ef35c80e0D76d32939F",
        threshold_high=2005,
        threshold_low=1990,
    )
    state = default_guard_state()
    got = _resolve_watched_pool(cfg, state)
    assert got.address.lower() == wp.address.lower()
    assert got.label == "USDC/WETH"


def test_resolve_guard_pool_address_from_flag() -> None:
    cfg = GuardConfig(
        pool="0xE0554a476A092703abdB3Ef35c80e0D76d32939F",
        threshold_high=1.0,
        threshold_low=0.5,
    )
    addr = resolve_guard_pool_address(cfg, default_guard_state())
    assert addr == "0xE0554a476A092703abdB3Ef35c80e0D76d32939F"


def test_resolve_guard_pool_address_from_state() -> None:
    cfg = GuardConfig(threshold_high=1.0, threshold_low=0.5)
    state = {
        **default_guard_state(),
        "pool_address": "0xe0554a476a092703abdb3ef35c80e0d76d32939f",
    }
    addr = resolve_guard_pool_address(cfg, state)
    assert addr == "0xE0554a476A092703abdB3Ef35c80e0D76d32939F"


def test_resolve_guard_pool_address_missing() -> None:
    import pytest

    cfg = GuardConfig(threshold_high=1.0, threshold_low=0.5)
    with pytest.raises(RuntimeError, match="Missing pool"):
        resolve_guard_pool_address(cfg, default_guard_state())


def test_resolve_guard_base_token_mismatch() -> None:
    import pytest

    from bds_agent.active_markets import WatchedPool

    wp = WatchedPool(
        address="0xE0554a476A092703abdB3Ef35c80e0D76d32939F",
        token0="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        token1="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        base_idx=1,
        label="USDC/WETH",
    )
    cfg = GuardConfig(
        pool=wp.address,
        base_token="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        threshold_high=1.0,
        threshold_low=0.5,
    )
    with pytest.raises(RuntimeError, match="does not match"):
        resolve_guard_base_token(cfg, wp)
