from __future__ import annotations

import typer

from bds_agent.llm.config_io import load_llm_json, save_llm_json
from bds_agent.llm.schema import AnthropicSection, LlmJson, OpenAISection, OllamaSection


def setup_anthropic_interactive() -> None:
    cfg = load_llm_json() or LlmJson()
    sec = cfg.anthropic or AnthropicSection()
    defaults = AnthropicSection()
    existing_key = (sec.api_key or "").strip()

    typer.echo(
        "Anthropic Messages API only (POST …/v1/messages). "
        "Base URL must be the API origin only (no /v1/messages suffix).",
    )
    base_default = sec.base_url or defaults.base_url
    base_in = typer.prompt("Base URL", default=base_default)
    model_default = sec.model or defaults.model
    model_in = typer.prompt("Model id", default=model_default)

    if existing_key:
        key_in = typer.prompt(
            "API key (leave empty to keep existing)",
            default="",
            hide_input=True,
            show_default=False,
        ).strip()
        if not key_in:
            key_in = existing_key
    else:
        key_in = typer.prompt("API key", hide_input=True).strip()
    if not key_in:
        typer.echo("Error: API key is required.", err=True)
        raise typer.Exit(1)

    cfg.anthropic = AnthropicSection(
        base_url=(base_in or base_default).strip(),
        model=(model_in or model_default).strip(),
        api_key=key_in,
        max_tokens=sec.max_tokens,
    )
    cfg.backend = "anthropic"
    save_llm_json(cfg)
    typer.echo(f"Saved LLM config: {_llm_path()}")


def setup_openai_interactive() -> None:
    cfg = load_llm_json() or LlmJson()
    sec = cfg.openai or OpenAISection()
    existing_key = (sec.api_key or "").strip()
    base_default = sec.base_url or "https://api.openai.com/v1"
    base_in = typer.prompt("OpenAI-compatible base URL", default=base_default)
    model_default = sec.model or "gpt-4o-mini"
    model_in = typer.prompt("Model id", default=model_default)
    if existing_key:
        key_in = typer.prompt(
            "API key (leave empty to keep existing)",
            default="",
            hide_input=True,
            show_default=False,
        ).strip()
        if not key_in:
            key_in = existing_key
    else:
        key_in = typer.prompt("API key", hide_input=True).strip()
    if not key_in:
        typer.echo("Error: API key is required.", err=True)
        raise typer.Exit(1)
    cfg.openai = OpenAISection(
        base_url=(base_in or base_default).strip(),
        model=(model_in or model_default).strip(),
        api_key=key_in,
        max_tokens=sec.max_tokens,
    )
    cfg.backend = "openai"
    save_llm_json(cfg)
    typer.echo(f"Saved LLM config: {_llm_path()}")


def setup_ollama_interactive() -> None:
    cfg = load_llm_json() or LlmJson()
    sec = cfg.ollama or OllamaSection()
    host = typer.prompt("Ollama host (host:port or http URL)", default=sec.host or "127.0.0.1:11434")
    model = typer.prompt("Model name", default=sec.model or "llama3.2")
    cfg.ollama = OllamaSection(host=host.strip(), model=model.strip())
    cfg.backend = "ollama"
    save_llm_json(cfg)
    typer.echo(f"Saved LLM config: {_llm_path()}")


def _llm_path() -> object:
    from bds_agent.paths import llm_json_path

    return llm_json_path()
