from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

import httpx

from bds_agent.llm.anthropic import AnthropicBackend, anthropic_api_key_from_env
from bds_agent.llm.apfel import ApfelBackend
from bds_agent.llm.config_io import load_llm_json
from bds_agent.llm.exceptions import LlmBackendNotConfiguredError, LlmError
from bds_agent.llm.local import LocalGgufBackend, local_available
from bds_agent.llm.ollama import OllamaBackend
from bds_agent.llm.openai import OpenAIBackend, openai_api_key_from_env


@runtime_checkable
class LLMBackend(Protocol):
    async def complete(self, system: str, user: str) -> str: ...


def effective_backend_name(
    *,
    cli_backend: str | None = None,
) -> str | None:
    """Resolved name before auto-detect: CLI > env > file."""
    if cli_backend and str(cli_backend).strip():
        return str(cli_backend).strip().lower()
    env = (os.environ.get("BDS_AGENT_LLM_BACKEND") or "").strip().lower()
    if env:
        return env
    cfg = load_llm_json()
    if cfg and cfg.backend and str(cfg.backend).strip():
        return str(cfg.backend).strip().lower()
    return None


def auto_detect_backend_name() -> str:
    """Pick a backend when none is configured (prefers keys in env)."""
    if anthropic_api_key_from_env():
        return "anthropic"
    if openai_api_key_from_env():
        return "openai"
    cfg = load_llm_json()
    if cfg:
        if cfg.anthropic and (cfg.anthropic.api_key or anthropic_api_key_from_env()):
            return "anthropic"
        if cfg.openai and (cfg.openai.api_key or openai_api_key_from_env()):
            return "openai"
    if ollama_reachable():
        return "ollama"
    if local_available():
        return "local"
    raise LlmBackendNotConfiguredError(
        "No LLM backend configured. Set ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN, "
        "OPENAI_API_KEY, start Ollama (or run: bds-agent llm setup ollama), "
        "or run: bds-agent llm setup anthropic",
    )


def ollama_reachable() -> bool:
    try:
        b = OllamaBackend.from_config(None)
        with httpx.Client(timeout=2.0) as c:
            r = c.get(f"{b.base_url}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


def resolve(
    *,
    backend: str | None = None,
    cli_backend: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> LLMBackend:
    """
    Return a backend for query/create.

    Precedence: `backend` arg > `cli_backend` > BDS_AGENT_LLM_BACKEND > llm.json > auto-detect.
    """
    name = (backend or cli_backend or "").strip() or None
    if not name:
        name = effective_backend_name(cli_backend=cli_backend)
    if not name:
        name = auto_detect_backend_name()
    name = str(name).strip().lower()
    cfg = load_llm_json()

    if name == "anthropic":
        return AnthropicBackend.from_config(
            cfg.anthropic if cfg else None,
            client=client,
        )
    if name == "openai":
        return OpenAIBackend.from_config(
            cfg.openai if cfg else None,
            client=client,
        )
    if name == "ollama":
        return OllamaBackend.from_config(
            cfg.ollama if cfg else None,
            client=client,
        )
    if name == "local":
        if not local_available():
            raise LlmBackendNotConfiguredError(
                "Local GGUF is not available yet. Set BDS_AGENT_LLM_BACKEND=anthropic or use ollama.",
            )
        return LocalGgufBackend()
    if name == "apfel":
        return ApfelBackend()
    raise LlmError(f"Unknown LLM backend: {name!r}")


def ensure_backend_configured(
    *,
    cli_backend: str | None = None,
) -> str:
    """Return resolved backend name or raise with setup hint."""
    name = effective_backend_name(cli_backend=cli_backend)
    if not name:
        name = auto_detect_backend_name()
    if name == "anthropic":
        cfg = load_llm_json()
        key = anthropic_api_key_from_env()
        if not key and (not cfg or not cfg.anthropic or not cfg.anthropic.api_key):
            raise LlmBackendNotConfiguredError(
                "No Anthropic API key. Export ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN "
                "or run: bds-agent llm setup anthropic",
            )
    if name == "openai":
        cfg = load_llm_json()
        key = openai_api_key_from_env()
        if not key and (not cfg or not cfg.openai or not cfg.openai.api_key):
            raise LlmBackendNotConfiguredError(
                "No OpenAI API key. Set OPENAI_API_KEY or run: bds-agent llm setup openai",
            )
    return name
