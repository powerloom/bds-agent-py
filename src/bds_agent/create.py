"""
Natural-language → ``agent.yaml`` (checkpoint step 12).

Uses the shared :mod:`bds_agent.llm` layer and :class:`bds_agent.config.AgentConfig` validation.
"""

from __future__ import annotations

import json
import re
from typing import Any

import yaml
from pydantic import ValidationError

from bds_agent.config import AgentConfig
from bds_agent.llm import LLMBackend
from bds_agent.query import catalog_endpoints_json_for_prompt


class CreateError(Exception):
    """LLM output could not be parsed as YAML or did not validate as ``AgentConfig``."""


_RULES_SPEC = """
Rule types (YAML list under ``rules:``, each item has ``type`` and type-specific keys):

- ``pool_filter``: ``pools`` — list of pool addresses (``0x...``), or omit / ``[]`` for all pools.
- ``token_filter``: ``tokens`` — list of token addresses, or ``[]`` for any token.
- ``min_usd``: ``threshold`` — USD amount as a **plain YAML number** (e.g. ``50000``). You may also use strings like ``\"50k\"`` or ``\"$50,000\"``; the runtime normalizes them. **Do not** emit placeholders such as a bare ``k`` or invalid tokens.
- ``volume_spike``: ``multiplier`` (number), ``window_epochs`` (optional int, default 10).
- ``price_move``: ``threshold_bps`` or legacy ``max_slippage_bps`` — basis points for sqrt price move between swaps.
"""

_SINKS_SPEC = """
Sink types (YAML list under ``sinks:``, each item has ``type`` and type-specific keys):

- ``stdout``: no extra keys.
- ``slack``: ``webhook_url`` — Slack Incoming Webhook URL.
- ``telegram``: ``bot_token``, ``chat_id``.
- ``discord``: ``webhook_url``.
- ``webhook``: ``url`` — generic POST JSON payload.
"""

_EXAMPLE_YAML = """
name: dex-alerts
version: 1
source:
  type: bds_stream
  endpoint: /mpp/stream/allTrades
  base_url: ${BDS_BASE_URL}
auth:
  profile: ${BDS_AGENT_PROFILE}
rules:
  - type: min_usd
    threshold: 50000
sinks:
  - type: stdout
verify: false
lifecycle:
  reconnect: true
  reconnect_delay: 5
  max_reconnects: 0
""".strip()


def _agent_json_schema_text() -> str:
    return json.dumps(AgentConfig.model_json_schema(), indent=2)


def build_create_system_prompt(catalog: dict[str, Any]) -> str:
    """System prompt: JSON Schema + rules + sinks + catalog + conventions."""
    cat_block = catalog_endpoints_json_for_prompt(catalog)
    parts = [
        "You are a compiler that outputs a single Powerloom bds-agent configuration document.",
        "",
        "Output requirements:",
        "- Output ONLY the YAML document for the agent configuration root mapping.",
        "- Do not add explanations before or after the YAML.",
        "- If you must use a markdown fence, use a single ```yaml fenced block and nothing else.",
        "",
        "Conventions:",
        "- Use ${BDS_BASE_URL} for source.base_url.",
        "- Use auth.profile: ${BDS_AGENT_PROFILE} unless the user explicitly describes embedding an API key string.",
        "- For ongoing DEX / swap / trade monitoring, prefer source.type: bds_stream and endpoint: /mpp/stream/allTrades from the catalog.",
        "- For min_usd.threshold, prefer a decimal number in YAML (e.g. threshold: 50000). If you use a string, it must be a full amount like 50k or $50,000 — never a lone letter or broken token.",
        "- Include verify: false unless the user explicitly asks for on-chain CID verification.",
        "- Include sensible lifecycle (reconnect, reconnect_delay, max_reconnects) when using bds_stream.",
        "",
        "JSON Schema for the document (follow field names and required sections):",
        _agent_json_schema_text(),
        "",
        "Rule types:",
        _RULES_SPEC,
        "",
        "Sink types:",
        _SINKS_SPEC,
        "",
        "Endpoint catalog (choose source.endpoint and source.type from these routes):",
        cat_block,
        "",
        "Minimal valid example (shape only; adapt rules/sinks to the user request):",
        _EXAMPLE_YAML,
    ]
    return "\n".join(parts)


def _strip_yaml_fence(s: str) -> str:
    t = s.strip()
    if not t.startswith("```"):
        return t
    lines = t.split("\n")
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_llm_yaml_to_dict(raw: str) -> dict[str, Any]:
    """Parse LLM output after stripping optional ```yaml fences."""
    text = _strip_yaml_fence(raw)
    if not text:
        raise CreateError("LLM returned empty output")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise CreateError(f"LLM output is not valid YAML: {e}") from e
    if not isinstance(data, dict):
        raise CreateError(f"YAML root must be a mapping, got {type(data).__name__}")
    return data


def validate_agent_dict(data: dict[str, Any]) -> AgentConfig:
    """Validate parsed YAML against :class:`AgentConfig`."""
    try:
        return AgentConfig.model_validate(data)
    except ValidationError as e:
        raise CreateError(f"Invalid agent configuration: {e}") from e


async def compile_nl_to_agent_config(
    prompt: str,
    catalog: dict[str, Any],
    backend: LLMBackend,
) -> AgentConfig:
    """NL → LLM → YAML → :class:`AgentConfig`."""
    p = (prompt or "").strip()
    if not p:
        raise CreateError("Prompt is empty")

    system = build_create_system_prompt(catalog)
    user = f"User request:\n{p}\n"
    raw = await backend.complete(system, user)
    data = parse_llm_yaml_to_dict(raw)
    return validate_agent_dict(data)


_SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def default_output_filename(cfg: AgentConfig) -> str:
    """Derive ``{name}.yaml`` with a filesystem-safe stem."""
    base = (cfg.name or "agent").strip()
    safe = _SAFE_FILENAME_RE.sub("-", base).strip("-")
    if not safe:
        safe = "agent"
    if len(safe) > 120:
        safe = safe[:120].rstrip("-")
    return f"{safe}.yaml"


def agent_config_to_yaml_text(cfg: AgentConfig) -> str:
    """Serialize validated config to YAML for writing."""
    payload = cfg.model_dump(mode="python", exclude_none=True)
    return yaml.safe_dump(
        payload,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
