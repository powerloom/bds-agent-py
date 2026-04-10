from __future__ import annotations

import os
from typing import Any

import httpx

from bds_agent.llm.exceptions import LlmBackendNotConfiguredError, LlmHttpError

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_TIMEOUT = 120.0


def anthropic_api_key_from_env() -> str | None:
    v = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if v:
        return v
    v = os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip()
    if v:
        return v
    return None


def anthropic_base_url_from_env(cfg_url: str) -> str:
    return (os.environ.get("ANTHROPIC_BASE_URL") or "").strip() or cfg_url


def anthropic_model_from_env(cfg_model: str) -> str:
    return (os.environ.get("ANTHROPIC_MODEL") or "").strip() or cfg_model


class AnthropicBackend:
    """Anthropic Messages API (`POST /v1/messages`) per Anthropic's specification."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        max_tokens: int = 4096,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None

    @classmethod
    def from_config(
        cls,
        section: Any,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> AnthropicBackend:
        key = anthropic_api_key_from_env()
        if not key and section and getattr(section, "api_key", None):
            key = str(section.api_key).strip() or None
        if not key:
            raise LlmBackendNotConfiguredError(
                "Anthropic-compatible backend: set ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN "
                "or run: bds-agent llm setup anthropic",
            )
        base = "https://api.anthropic.com"
        model = "claude-sonnet-4-20250514"
        max_tokens = 4096
        if section is not None:
            base = getattr(section, "base_url", None) or base
            model = getattr(section, "model", None) or model
            max_tokens = int(getattr(section, "max_tokens", max_tokens) or max_tokens)
        base = anthropic_base_url_from_env(base)
        model = anthropic_model_from_env(model)
        return cls(
            api_key=key,
            base_url=base,
            model=model,
            max_tokens=max_tokens,
            client=client,
        )

    async def complete(self, system: str, user: str) -> str:
        url = f"{self._base_url}/v1/messages"
        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": [{"role": "user", "content": user}],
        }
        if system.strip():
            payload["system"] = system
        headers = {
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
            "x-api-key": self._api_key,
        }
        own = self._owns_client
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            r = await client.post(url, json=payload, headers=headers)
            if r.status_code >= 400:
                raise LlmHttpError(
                    _format_anthropic_error(r),
                    status_code=r.status_code,
                )
            data = r.json()
        finally:
            if own:
                await client.aclose()
        return _extract_text(data)


def _format_anthropic_error(r: httpx.Response) -> str:
    try:
        body = r.json()
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict) and err.get("message"):
                return f"Anthropic API HTTP {r.status_code}: {err['message']}"
    except Exception:
        pass
    return f"Anthropic API HTTP {r.status_code}: {r.text[:500]}"


def _extract_text(data: dict[str, Any]) -> str:
    parts: list[str] = []
    for block in data.get("content") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
    if not parts:
        raise LlmHttpError("Anthropic API: empty or unrecognized response content", status_code=None)
    return "".join(parts)
