"""
Natural-language → BDS endpoint + parameters (checkpoint step 10).

Uses the shared :mod:`bds_agent.llm` layer and the same ``endpoints.json`` catalog as ``run`` / ``mcp``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from bds_agent.llm import LLMBackend
from bds_agent.mcp.registry import EndpointTool, build_endpoint_tools, invoke_tool


class QueryError(Exception):
    """Failed to map NL to a catalog route or to execute it."""


def _strip_json_fence(s: str) -> str:
    t = s.strip()
    if not t.startswith("```"):
        return t
    lines = t.split("\n")
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_llm_json(raw: str) -> dict[str, Any]:
    s = _strip_json_fence(raw)
    try:
        data = json.loads(s)
    except json.JSONDecodeError as e:
        # Try to extract a single JSON object if the model added prose
        m = re.search(r"\{[\s\S]*\}", s)
        if m:
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                raise QueryError(f"LLM response is not valid JSON: {e}") from e
        else:
            raise QueryError(f"LLM response is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise QueryError("LLM JSON must be an object")
    return data


def _catalog_path_templates(catalog: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    eps = catalog.get("endpoints")
    if not isinstance(eps, list):
        return out
    for e in eps:
        if isinstance(e, dict) and isinstance(e.get("path"), str):
            out.add(e["path"])
    return out


def catalog_endpoints_json_for_prompt(catalog: dict[str, Any]) -> str:
    """Compact JSON for the query-translation system prompt."""
    eps = catalog.get("endpoints")
    if not isinstance(eps, list):
        return "[]"
    slim: list[dict[str, Any]] = []
    for e in eps:
        if not isinstance(e, dict):
            continue
        p = e.get("path")
        if not isinstance(p, str):
            continue
        slim.append(
            {
                "path": p,
                "method": str(e.get("method") or "GET").upper(),
                "sse": bool(e.get("sse")),
                "params": e.get("params") if isinstance(e.get("params"), list) else [],
                "description": str(e.get("description") or "")[:500],
            },
        )
    return json.dumps(slim, indent=2)


QUERY_SYSTEM_PROMPT = """You are a BDS API router. Given a user question, choose exactly one HTTP route from the catalog below and fill parameters.

Rules:
- Output ONLY a single JSON object with no markdown code fences.
- Keys must be:
  - "path": string — MUST exactly match one "path" value from the catalog (including curly-brace placeholders such as {block_number} when the route defines them).
  - "params": object — keys are parameter names from that route's "params" (path and query). Use integers for integer types. Omit optional params if unknown.
  - "rationale": string (optional) — one short sentence explaining the choice.

If the question cannot be mapped to any catalog route, set "path" to "" and "params" to an empty object and explain in "rationale".

Catalog (endpoints.json):
"""


@dataclass(frozen=True)
class QueryResolution:
    """Resolved route and arguments for :func:`invoke_tool` / display."""

    path_template: str
    arguments: dict[str, Any]
    sse: bool
    rationale: str | None


def find_tool_by_path_template(tools: list[EndpointTool], path_template: str) -> EndpointTool | None:
    for t in tools:
        if t.path_template == path_template:
            return t
    return None


def resolution_from_llm_json(
    data: dict[str, Any],
    tools: list[EndpointTool],
    *,
    catalog_paths: set[str],
) -> QueryResolution:
    path = data.get("path")
    if not isinstance(path, str):
        raise QueryError('LLM JSON missing string "path"')
    path = path.strip()
    if not path:
        r = data.get("rationale")
        raise QueryError(
            f"Could not map question to a catalog route. {r if isinstance(r, str) else ''}".strip(),
        )
    if path not in catalog_paths:
        raise QueryError(f"Unknown path {path!r} — not in catalog")

    tool = find_tool_by_path_template(tools, path)
    if tool is None:
        raise QueryError(f"No tool for path {path!r}")

    raw_params = data.get("params")
    if raw_params is None:
        raw_params = {}
    if not isinstance(raw_params, dict):
        raise QueryError('"params" must be an object')

    arguments: dict[str, Any] = {}
    for k, v in raw_params.items():
        if not isinstance(k, str):
            continue
        arguments[k] = v

    if tool.is_sse and "max_events" not in arguments:
        arguments["max_events"] = 5

    r = data.get("rationale")
    rationale = str(r).strip() if isinstance(r, str) else None

    return QueryResolution(
        path_template=path,
        arguments=arguments,
        sse=tool.is_sse,
        rationale=rationale,
    )


async def translate_nl(
    text: str,
    catalog: dict[str, Any],
    backend: LLMBackend,
) -> QueryResolution:
    """Map natural language to a catalog route + parameters using the LLM."""
    t = (text or "").strip()
    if not t:
        raise QueryError("Question text is empty")

    tools = build_endpoint_tools(catalog)
    paths = _catalog_path_templates(catalog)
    if not paths:
        raise QueryError("Catalog has no endpoints")

    system = QUERY_SYSTEM_PROMPT + catalog_endpoints_json_for_prompt(catalog)
    user = f"User question:\n{t}\n"
    raw = await backend.complete(system, user)
    data = _parse_llm_json(raw)
    return resolution_from_llm_json(data, tools, catalog_paths=paths)


async def execute_resolution(
    *,
    resolution: QueryResolution,
    catalog: dict[str, Any],
    base_url: str,
    api_key: str,
) -> dict[str, Any]:
    """Execute a resolution via the same HTTP path as MCP tools."""
    tools = build_endpoint_tools(catalog)
    tool = find_tool_by_path_template(tools, resolution.path_template)
    if tool is None:
        raise QueryError(f"No tool for path {resolution.path_template!r}")
    return await invoke_tool(
        tool,
        resolution.arguments,
        base_url=base_url,
        api_key=api_key,
    )
