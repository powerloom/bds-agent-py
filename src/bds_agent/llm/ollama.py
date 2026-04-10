from __future__ import annotations

import os
from typing import Any
import httpx

from bds_agent.llm.exceptions import LlmHttpError

DEFAULT_TIMEOUT = 120.0


def _normalize_host(host: str) -> str:
    h = host.strip()
    if h.startswith("http://") or h.startswith("https://"):
        return h.rstrip("/")
    return f"http://{h.strip()}"


class OllamaBackend:
    """Ollama HTTP API (`POST /api/chat`)."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None

    @property
    def base_url(self) -> str:
        return self._base_url

    @classmethod
    def from_config(cls, section: Any, *, client: httpx.AsyncClient | None = None) -> OllamaBackend:
        host = "127.0.0.1:11434"
        model = "llama3.2"
        if section is not None:
            host = getattr(section, "host", None) or host
            model = getattr(section, "model", None) or model
        env_host = (os.environ.get("OLLAMA_HOST") or "").strip()
        if env_host:
            host = env_host
        env_model = (os.environ.get("OLLAMA_MODEL") or "").strip()
        if env_model:
            model = env_model
        base = _normalize_host(host)
        return cls(base_url=base, model=model, client=client)

    async def complete(self, system: str, user: str) -> str:
        url = f"{self._base_url}/api/chat"
        messages: list[dict[str, str]] = []
        if system.strip():
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
        }
        own = self._owns_client
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            r = await client.post(url, json=payload)
            if r.status_code >= 400:
                raise LlmHttpError(
                    f"Ollama HTTP {r.status_code}: {r.text[:500]}",
                    status_code=r.status_code,
                )
            data = r.json()
        finally:
            if own:
                await client.aclose()
        msg = data.get("message") if isinstance(data, dict) else None
        if isinstance(msg, dict) and isinstance(msg.get("content"), str):
            return msg["content"]
        raise LlmHttpError("Ollama: missing message.content in response", status_code=None)
