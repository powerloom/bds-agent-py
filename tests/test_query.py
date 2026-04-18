from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from bds_agent.mcp.registry import build_endpoint_tools
from bds_agent.query import (
    QueryError,
    _parse_llm_json,
    catalog_endpoints_json_for_prompt,
    resolution_from_llm_json,
    translate_nl,
)


@pytest.fixture
def minimal_catalog() -> dict:
    path = Path(__file__).parent / "fixtures" / "endpoints.minimal.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_parse_llm_json_tolerates_trailing_prose() -> None:
    """Local models often append text after the JSON object (json.loads → Extra data)."""
    raw = (
        '{"path": "/mpp/foo", "params": {"a": 1}, "rationale": "x"}\n\n'
        "Let me know if you need anything else."
    )
    d = _parse_llm_json(raw)
    assert d["path"] == "/mpp/foo"


def test_parse_llm_json_prose_before_object() -> None:
    raw = 'Sure, here is the route:\n{"path": "/x", "params": {}}'
    d = _parse_llm_json(raw)
    assert d["path"] == "/x"


def test_parse_llm_json_markdown_fence() -> None:
    raw = '```json\n{"path": "/y", "params": {}}\n```\n'
    d = _parse_llm_json(raw)
    assert d["path"] == "/y"


def test_catalog_endpoints_json_for_prompt(minimal_catalog: dict) -> None:
    s = catalog_endpoints_json_for_prompt(minimal_catalog)
    assert "/mpp/stream/allTrades" in s
    assert "block_number" in s


def test_resolution_from_llm_json_ok(minimal_catalog: dict) -> None:
    tools = build_endpoint_tools(minimal_catalog)
    paths = {t.path_template for t in tools}
    data = {
        "path": "/mpp/snapshot/allTrades/{block_number}",
        "params": {"block_number": 99},
        "rationale": "test",
    }
    res = resolution_from_llm_json(data, tools, catalog_paths=paths)
    assert res.path_template == "/mpp/snapshot/allTrades/{block_number}"
    assert res.arguments["block_number"] == 99
    assert res.sse is False


def test_resolution_from_llm_json_unknown_path(minimal_catalog: dict) -> None:
    tools = build_endpoint_tools(minimal_catalog)
    paths = {t.path_template for t in tools}
    data = {"path": "/mpp/does/not/exist", "params": {}}
    with pytest.raises(QueryError, match="not in catalog"):
        resolution_from_llm_json(data, tools, catalog_paths=paths)


def test_resolution_sse_adds_max_events(minimal_catalog: dict) -> None:
    tools = build_endpoint_tools(minimal_catalog)
    paths = {t.path_template for t in tools}
    data = {
        "path": "/mpp/stream/allTrades",
        "params": {},
    }
    res = resolution_from_llm_json(data, tools, catalog_paths=paths)
    assert res.sse is True
    assert res.arguments.get("max_events") == 5


def test_translate_nl_mock_backend(minimal_catalog: dict) -> None:
    class Fake:
        async def complete(self, system: str, user: str) -> str:
            assert "Catalog" in system or "endpoints" in system
            return json.dumps(
                {
                    "path": "/mpp/snapshot/allTrades/{block_number}",
                    "params": {"block_number": 1},
                    "rationale": "mock",
                },
            )

    async def run() -> None:
        res = await translate_nl("give me trades for block 1", minimal_catalog, Fake())
        assert res.path_template.endswith("{block_number}")
        assert res.arguments["block_number"] == 1

    asyncio.run(run())
