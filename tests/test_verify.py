from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from eth_abi import encode
from pydantic import ValidationError

from bds_agent.config import AgentConfig, AuthConfig, SourceConfig
from bds_agent.verify import (
    VerifyError,
    parse_verification,
    resolve_verify_data_market,
    resolve_verify_protocol_state,
    resolve_verify_rpc_url,
    verify_cid,
)


def _minimal_agent(**kwargs: object) -> AgentConfig:
    base = dict(
        name="t",
        source={"type": "bds_stream", "endpoint": "/mpp/stream/allTrades", "base_url": "http://127.0.0.1:9"},
        auth={"api_key": "sk"},
    )
    base.update(kwargs)
    return AgentConfig.model_validate(base)


def test_parse_verification_ok() -> None:
    p = parse_verification(
        {
            "epoch": 1,
            "snapshot": {},
            "verification": {
                "cid": "QmX",
                "epochId": 5,
                "projectId": "proj:1",
                "protocolState": "0x1d0e010Ff11b781CA1dE34BD25a0037203e25E2a",
                "dataMarket": "0x26c44e5CcEB7Fe69Cffc933838CF40286b2dc01a",
            },
        },
    )
    assert p is not None
    assert p.cid == "QmX"
    assert p.epoch_id == 5
    assert p.project_id == "proj:1"


def test_parse_verification_missing() -> None:
    assert parse_verification({"epoch": 1, "snapshot": {}}) is None


def test_resolve_verify_rpc_url_yaml_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POWERLOOM_RPC_URL", "http://from-env")
    cfg = _minimal_agent(verify_rpc_url="http://from-yaml")
    assert resolve_verify_rpc_url(cfg) == "http://from-yaml"


def test_resolve_verify_protocol_state_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    from bds_agent.verify import VerificationPayload

    monkeypatch.delenv("POWERLOOM_PROTOCOL_STATE", raising=False)
    vp = VerificationPayload(
        cid="x",
        epoch_id=1,
        project_id="p",
        protocol_state="0x1111111111111111111111111111111111111111",
        data_market="0x2222222222222222222222222222222222222222",
    )
    cfg = _minimal_agent(verify_protocol_state="0x3333333333333333333333333333333333333333")
    assert resolve_verify_protocol_state(cfg, vp) == "0x3333333333333333333333333333333333333333"


def test_resolve_verify_data_market_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    from bds_agent.verify import VerificationPayload

    monkeypatch.delenv("POWERLOOM_DATA_MARKET", raising=False)
    vp = VerificationPayload(
        cid="x",
        epoch_id=1,
        project_id="p",
        protocol_state="0x1d0e010Ff11b781CA1dE34BD25a0037203e25E2a",
        data_market="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )
    cfg = _minimal_agent(verify_data_market="0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    assert resolve_verify_data_market(cfg, vp) == "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


async def _verify_cid_with_mock_client(*, match_cid: str, stream_cid: str) -> None:
    from bds_agent.verify import VerificationPayload

    ret_bytes = encode(["string", "uint8"], [match_cid, 0])

    class FakeResp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"jsonrpc": "2.0", "id": 1, "result": "0x" + ret_bytes.hex()}

    class FakeClient:
        async def post(self, url: str, json: dict | None = None) -> FakeResp:
            return FakeResp()

        async def aclose(self) -> None:
            pass

    vp = VerificationPayload(
        cid=stream_cid,
        epoch_id=1,
        project_id="allTradesSnapshot:0xabc:ns",
        protocol_state="0x1d0e010Ff11b781CA1dE34BD25a0037203e25E2a",
        data_market="0x26c44e5CcEB7Fe69Cffc933838CF40286b2dc01a",
    )
    r = await verify_cid(
        vp,
        rpc_url="http://127.0.0.1:9",
        protocol_state=vp.protocol_state,
        client=FakeClient(),
    )
    assert r.match == (stream_cid == match_cid)
    assert r.stream_cid == stream_cid.strip()
    assert r.on_chain_cid == match_cid


def test_verify_cid_match() -> None:
    asyncio.run(_verify_cid_with_mock_client(match_cid="bafyBEEF", stream_cid="bafyBEEF"))


def test_verify_cid_mismatch() -> None:
    asyncio.run(_verify_cid_with_mock_client(match_cid="bafyOnChain", stream_cid="bafyStream"))


def test_verify_cid_rpc_error() -> None:
    from bds_agent.verify import VerificationPayload

    class BadClient:
        async def post(self, url: str, json: dict | None = None) -> MagicMock:
            raise httpx.ConnectError("network", request=MagicMock())

        async def aclose(self) -> None:
            pass

    vp = VerificationPayload(
        cid="x",
        epoch_id=1,
        project_id="p",
        protocol_state="0x1d0e010Ff11b781CA1dE34BD25a0037203e25E2a",
        data_market="0x26c44e5CcEB7Fe69Cffc933838CF40286b2dc01a",
    )

    async def run() -> None:
        with pytest.raises(VerifyError):
            await verify_cid(
                vp,
                rpc_url="http://x",
                protocol_state=vp.protocol_state,
                client=BadClient(),
            )

    asyncio.run(run())


def test_agent_config_accepts_verify_options() -> None:
    cfg = _minimal_agent(
        verify=True,
        verify_rpc_url="http://rpc.example",
        verify_protocol_state="0x1d0e010Ff11b781CA1dE34BD25a0037203e25E2a",
        verify_data_market="0x26c44e5CcEB7Fe69Cffc933838CF40286b2dc01a",
    )
    assert cfg.verify_rpc_url == "http://rpc.example"
    assert cfg.verify_protocol_state is not None
    assert cfg.verify_data_market is not None


def test_agent_config_rejects_unknown_top_level() -> None:
    with pytest.raises(ValidationError):
        AgentConfig.model_validate(
            {
                "name": "t",
                "source": {"type": "bds_stream", "endpoint": "/x", "base_url": "http://a"},
                "auth": {"api_key": "k"},
                "not_a_real_field": True,
            },
        )


def test_resolve_rpc_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POWERLOOM_RPC_URL", "http://rpc-env")
    cfg = _minimal_agent()
    assert resolve_verify_rpc_url(cfg) == "http://rpc-env"


def test_resolve_rpc_from_profile_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("POWERLOOM_RPC_URL", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    profiles = tmp_path / ".config" / "bds-agent" / "profiles"
    profiles.mkdir(parents=True)
    import json

    (profiles / "p1.json").write_text(
        json.dumps(
            {
                "api_key": "sk",
                "powerloom_rpc_url": "http://rpc-profile",
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BDS_AGENT_PROFILE", "p1")
    cfg = _minimal_agent()
    assert resolve_verify_rpc_url(cfg) == "http://rpc-profile"
