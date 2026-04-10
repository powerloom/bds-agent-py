from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from bds_agent.mcp.registry import (
    build_endpoint_tools,
    find_tool,
    invoke_tool,
    tool_name_from_path,
    to_mcp_tools,
)


def test_tool_name_unique() -> None:
    used: set[str] = set()
    a = tool_name_from_path("/mpp/a/b", "GET", used)
    b = tool_name_from_path("/mpp/a/c", "GET", used)
    assert a != b
    assert a.startswith("bds_")


def test_tool_name_path_param_variants_not_colliding() -> None:
    """Routes that differ only by path segments must not share one slug + _2."""
    used: set[str] = set()
    no_block = tool_name_from_path("/mpp/ethPrice", "GET", used)
    with_block = tool_name_from_path("/mpp/ethPrice/{block_number}", "GET", used)
    assert no_block == "bds_mpp_ethPrice"
    assert with_block == "bds_mpp_ethPrice_block_number"
    assert not with_block.endswith("_2")


def test_build_endpoint_tools_minimal() -> None:
    path = Path(__file__).parent / "fixtures" / "endpoints.minimal.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    tools = build_endpoint_tools(catalog)
    assert len(tools) == 2
    names = {t.name for t in tools}
    assert len(names) == 2
    snap = next(t for t in tools if "alltrades" in t.name.lower() and not t.is_sse)
    assert "{block_number}" in snap.path_template
    stream = next(t for t in tools if t.is_sse)
    assert stream.path_template == "/mpp/stream/allTrades"


def test_to_mcp_tools_schema() -> None:
    path = Path(__file__).parent / "fixtures" / "endpoints.minimal.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    tools = build_endpoint_tools(catalog)
    mcp = to_mcp_tools(tools)
    assert len(mcp) == 2
    for t in mcp:
        assert t.inputSchema.get("type") == "object"


def test_invoke_fetch_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    path = Path(__file__).parent / "fixtures" / "endpoints.minimal.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    tools = build_endpoint_tools(catalog)
    spec = find_tool(tools, next(t.name for t in tools if not t.is_sse))
    assert spec is not None

    async def fake_fetch(
        base_url: str,
        endpoint: str,
        api_key: str,
        **params: object,
    ):
        from bds_agent.client import FetchResult

        assert "/mpp/snapshot/allTrades/123" == endpoint
        assert api_key == "k"
        return FetchResult(data={"ok": True}, status_code=200, credit_balance=10)

    monkeypatch.setattr("bds_agent.mcp.registry.fetch", fake_fetch)

    async def run() -> None:
        out = await invoke_tool(
            spec,
            {"block_number": 123},
            base_url="https://node.example",
            api_key="k",
        )
        assert out["data"] == {"ok": True}
        assert out["credit_balance"] == 10

    asyncio.run(run())
