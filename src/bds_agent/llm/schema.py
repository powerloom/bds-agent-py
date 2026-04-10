from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel

BackendName = Literal["local", "apfel", "ollama", "anthropic", "openai"]


class LocalSection(BaseModel):
    model_path: str = ""
    model_url: str = ""
    n_ctx: int = 4096
    n_gpu_layers: int = 0


class OllamaSection(BaseModel):
    host: str = "127.0.0.1:11434"
    model: str = "llama3.2"


class AnthropicSection(BaseModel):
    base_url: str = "https://api.anthropic.com"
    model: str = "claude-sonnet-4-20250514"
    api_key: str | None = None
    max_tokens: int = 4096


class OpenAISection(BaseModel):
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    api_key: str | None = None
    max_tokens: int = 4096


class LlmJson(BaseModel):
    """On-disk shape for ~/.config/bds-agent/llm.json."""

    backend: str | None = None
    local: LocalSection | None = None
    ollama: OllamaSection | None = None
    anthropic: AnthropicSection | None = None
    openai: OpenAISection | None = None


def expand_model_path(path: str) -> Path:
    return Path(path).expanduser().resolve()
