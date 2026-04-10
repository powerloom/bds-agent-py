from __future__ import annotations

import os
from typing import Any

import httpx

from bds_agent.llm.exceptions import LlmBackendNotConfiguredError, LlmHttpError

DEFAULT_TIMEOUT = 120.0


def openai_api_key_from_env() -> str | None:
    v = os.environ.get("OPENAI_API_KEY", "").strip()
    return v or None


def openai_base_url_from_env(cfg_url: str) -> str:
    return (os.environ.get("OPENAI_BASE_URL") or "").strip() or cfg_url


def openai_model_from_env(cfg_model: str) -> str:
    return (os.environ.get("OPENAI_MODEL") or "").strip() or cfg_model


class OpenAIBackend:
    """OpenAI Chat Completions (`POST .../chat/completions`) for OpenAI-compatible servers."""

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
    def from_config(cls, section: Any, *, client: httpx.AsyncClient | None = None) -> OpenAIBackend:
        key = openai_api_key_from_env()
        if not key and section and getattr(section, "api_key", None):
            key = str(section.api_key).strip() or None
        if not key:
            raise LlmBackendNotConfiguredError(
                "OpenAI-compatible backend: set OPENAI_API_KEY or run: bds-agent llm setup openai",
            )
        base = "https://api.openai.com/v1"
        model = "gpt-4o-mini"
        max_tokens = 4096
        if section is not None:
            base = getattr(section, "base_url", None) or base
            model = getattr(section, "model", None) or model
            max_tokens = int(getattr(section, "max_tokens", max_tokens) or max_tokens)
        base = openai_base_url_from_env(base)
        model = openai_model_from_env(model)
        return cls(
            api_key=key,
            base_url=base,
            model=model,
            max_tokens=max_tokens,
            client=client,
        )

    async def complete(self, system: str, user: str) -> str:
        url = f"{self._base_url}/chat/completions"
        messages: list[dict[str, str]] = []
        if system.strip():
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        payload = {
            "model": self._model,
            "messages": messages,
            "max_tokens": self._max_tokens,
        }
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self._api_key}",
        }
        own = self._owns_client
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            r = await client.post(url, json=payload, headers=headers)
            if r.status_code >= 400:
                raise LlmHttpError(_format_openai_error(r), status_code=r.status_code)
            data = r.json()
        finally:
            if own:
                await client.aclose()
        return _extract_chat_text(data)


def _format_openai_error(r: httpx.Response) -> str:
    try:
        body = r.json()
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict) and err.get("message"):
            return f"OpenAI-compatible HTTP {r.status_code}: {err['message']}"
    except Exception:
        pass
    return f"OpenAI-compatible HTTP {r.status_code}: {r.text[:500]}"


def _extract_chat_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LlmHttpError("OpenAI-compatible: empty choices", status_code=None)
    msg = choices[0].get("message") if isinstance(choices[0], dict) else None
    if isinstance(msg, dict) and isinstance(msg.get("content"), str):
        return msg["content"]
    raise LlmHttpError("OpenAI-compatible: unrecognized response shape", status_code=None)
