from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from bds_agent.llm.anthropic import AnthropicBackend, anthropic_api_key_from_env
from bds_agent.llm.config_io import load_llm_json, save_llm_json
from bds_agent.llm.exceptions import LlmBackendNotConfiguredError
from bds_agent.llm.resolve import effective_backend_name, resolve
from bds_agent.llm.schema import AnthropicSection, LlmJson


def test_anthropic_api_key_prefers_explicit_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", " sk-a ")
    assert anthropic_api_key_from_env() == "sk-a"


def test_anthropic_api_key_auth_token_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token-from-env")
    assert anthropic_api_key_from_env() == "token-from-env"


def test_anthropic_complete_extracts_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        assert body["model"] == "m"
        assert body["messages"][0]["role"] == "user"
        return httpx.Response(200, json={"content": [{"type": "text", "text": "OK"}]})

    transport = httpx.MockTransport(handler)

    async def run() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            b = AnthropicBackend(
                api_key="k",
                base_url="https://example.com",
                model="m",
                client=client,
            )
            out = await b.complete("sys", "user")
            assert out == "OK"

    asyncio.run(run())


def test_effective_backend_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BDS_AGENT_LLM_BACKEND", "openai")
    assert effective_backend_name(cli_backend=None) == "openai"


def test_resolve_anthropic_from_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("BDS_AGENT_LLM_BACKEND", "anthropic")
    monkeypatch.setenv("HOME", str(tmp_path))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"content": [{"type": "text", "text": "pong"}]})

    transport = httpx.MockTransport(handler)

    async def run() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            b = resolve(client=client)
            out = await b.complete("s", "u")
            assert out == "pong"

    asyncio.run(run())


def test_load_save_llm_json_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = LlmJson(
        backend="anthropic",
        anthropic=AnthropicSection(
            base_url="https://api.anthropic.com",
            model="claude-sonnet-4-20250514",
            api_key="secret",
        ),
    )
    save_llm_json(cfg)
    loaded = load_llm_json()
    assert loaded is not None
    assert loaded.backend == "anthropic"
    assert loaded.anthropic is not None
    assert loaded.anthropic.model == "claude-sonnet-4-20250514"
    assert loaded.anthropic.api_key == "secret"


def test_resolve_raises_without_keys(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("BDS_AGENT_LLM_BACKEND", "anthropic")

    with pytest.raises(LlmBackendNotConfiguredError):
        resolve()
