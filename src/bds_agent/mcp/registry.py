from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import mcp.types as types

from bds_agent.client import fetch, stream

# MCP tool names: SEP-986 [A-Za-z0-9._-]{1,128}
_SLUG_CLEAN = re.compile(r"[^a-zA-Z0-9._-]+")


@dataclass
class EndpointTool:
    """One catalog entry mapped to an MCP tool."""

    name: str
    path_template: str
    method: str
    description: str
    is_sse: bool
    path_param_names: list[str]
    query_param_specs: list[dict[str, Any]]
    path_param_specs: list[dict[str, Any]]


def tool_name_from_path(path: str, method: str, used: set[str]) -> str:
    """Derive a unique MCP tool name from route path."""
    # Keep `{param}` names so `/ethPrice` and `/ethPrice/{block_number}` do not
    # collapse to the same slug (which previously forced `bds_*` vs `bds_*_2`).
    stripped = re.sub(r"\{([^}]+)\}", r"_\1", path)
    stripped = stripped.strip("/").replace("/", "_").replace(".", "_")
    base = _SLUG_CLEAN.sub("_", stripped)
    base = re.sub(r"_+", "_", base).strip("._-") or "endpoint"
    name = f"bds_{base}"[:120]
    if method.upper() != "GET":
        name = f"{name}_{method.lower()}"[:128]
    if name in used:
        n = 2
        while f"{name}_{n}" in used and n < 1000:
            n += 1
        name = f"{name}_{n}"[:128]
    used.add(name)
    return name


def _param_specs(entry: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    path_specs: list[dict[str, Any]] = []
    query_specs: list[dict[str, Any]] = []
    raw = entry.get("params")
    if not isinstance(raw, list):
        return path_specs, query_specs
    for p in raw:
        if not isinstance(p, dict):
            continue
        loc = str(p.get("in") or "query")
        if loc == "path":
            path_specs.append(p)
        elif loc == "query":
            query_specs.append(p)
    return path_specs, query_specs


def _path_param_names(path: str) -> list[str]:
    return re.findall(r"\{([^}]+)\}", path)


def _json_schema_properties(
    path_specs: list[dict[str, Any]],
    query_specs: list[dict[str, Any]],
    *,
    is_sse: bool,
) -> tuple[dict[str, Any], list[str]]:
    properties: dict[str, Any] = {}
    required: list[str] = []

    def add_from_spec(p: dict[str, Any]) -> None:
        name = p.get("name")
        if not isinstance(name, str) or not name:
            return
        typ = p.get("type")
        if typ == "integer":
            properties[name] = {"type": "integer"}
        elif typ == "number":
            properties[name] = {"type": "number"}
        elif typ == "boolean":
            properties[name] = {"type": "boolean"}
        else:
            properties[name] = {"type": "string"}
        req = p.get("required", False)
        if req is True:
            required.append(name)

    for p in path_specs:
        add_from_spec(p)
    for p in query_specs:
        add_from_spec(p)

    if is_sse:
        properties["max_events"] = {
            "type": "integer",
            "description": "Stop after this many epoch events (default 5, max 50).",
        }

    return properties, required


def build_endpoint_tools(catalog: dict[str, Any]) -> list[EndpointTool]:
    eps = catalog.get("endpoints")
    if not isinstance(eps, list):
        return []
    used_names: set[str] = set()
    out: list[EndpointTool] = []
    for entry in eps:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if not isinstance(path, str) or not path.startswith("/"):
            continue
        method = str(entry.get("method") or "GET").upper()
        desc = str(entry.get("description") or path).strip()
        is_sse = bool(entry.get("sse"))
        path_specs, query_specs = _param_specs(entry)
        names_in_path = _path_param_names(path)
        name = tool_name_from_path(path, method, used_names)
        out.append(
            EndpointTool(
                name=name,
                path_template=path,
                method=method,
                description=desc,
                is_sse=is_sse,
                path_param_names=names_in_path,
                query_param_specs=query_specs,
                path_param_specs=path_specs,
            ),
        )
    return out


def to_mcp_tools(tools: list[EndpointTool]) -> list[types.Tool]:
    mcp_list: list[types.Tool] = []
    for t in tools:
        props, req = _json_schema_properties(
            t.path_param_specs,
            t.query_param_specs,
            is_sse=t.is_sse,
        )
        schema: dict[str, Any] = {
            "type": "object",
            "properties": props,
        }
        if req:
            schema["required"] = req
        mcp_list.append(
            types.Tool(
                name=t.name,
                description=t.description[:5000] if t.description else None,
                inputSchema=schema,
            ),
        )
    return mcp_list


def _substitute_path(path_template: str, args: dict[str, Any]) -> str:
    out = path_template
    for key, val in args.items():
        out = out.replace("{" + key + "}", str(val))
    if "{" in out:
        raise ValueError(f"Missing path parameter(s) for {path_template!r}")
    return out


def _query_kwargs(
    query_specs: list[dict[str, Any]],
    args: dict[str, Any],
) -> dict[str, Any]:
    q: dict[str, Any] = {}
    for spec in query_specs:
        n = spec.get("name")
        if isinstance(n, str) and n in args and args[n] is not None:
            q[n] = args[n]
    return q


async def invoke_tool(
    spec: EndpointTool,
    arguments: dict[str, Any],
    *,
    base_url: str,
    api_key: str,
) -> dict[str, Any]:
    """Execute one tool call; returns JSON-serializable result."""
    args = dict(arguments)
    max_events = 5
    if spec.is_sse and "max_events" in args:
        try:
            max_events = int(args.pop("max_events"))
        except (TypeError, ValueError):
            max_events = 5
    max_events = max(1, min(50, max_events))

    if spec.method != "GET":
        raise ValueError(f"Unsupported method {spec.method} for {spec.name}")

    path = _substitute_path(spec.path_template, args)
    query = _query_kwargs(spec.query_param_specs, args)

    if spec.is_sse:
        events: list[dict[str, Any]] = []
        last_credit: int | None = None
        async for chunk in stream(
            base_url,
            path,
            api_key,
            query_params=query or None,
            max_events=max_events,
            reconnect=False,
        ):
            events.append(chunk.data)
            last_credit = chunk.credit_balance
        return {"events": events, "credit_balance": last_credit}

    result = await fetch(base_url, path, api_key, **query)
    out: dict[str, Any] = {"data": result.data, "credit_balance": result.credit_balance}
    return out


def find_tool(tools: list[EndpointTool], name: str) -> EndpointTool | None:
    for t in tools:
        if t.name == name:
            return t
    return None
