from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from bds_agent.config import AgentConfig
from bds_agent.create import (
    CreateError,
    build_create_system_prompt,
    compile_nl_to_agent_config,
    default_output_filename,
    parse_llm_yaml_to_dict,
    validate_agent_dict,
)
from bds_agent.query import catalog_endpoints_json_for_prompt


@pytest.fixture
def minimal_catalog() -> dict:
    path = Path(__file__).parent / "fixtures" / "endpoints.minimal.json"
    return json.loads(path.read_text(encoding="utf-8"))


_GOLDEN_YAML = """
name: test-create-agent
version: 1
source:
  type: bds_stream
  endpoint: /mpp/stream/allTrades
  base_url: ${BDS_BASE_URL}
auth:
  profile: ${BDS_AGENT_PROFILE}
rules:
  - type: min_usd
    threshold: 100
sinks:
  - type: stdout
verify: false
"""


def test_strip_yaml_fence_plain() -> None:
    d = parse_llm_yaml_to_dict(_GOLDEN_YAML)
    assert d["name"] == "test-create-agent"
    assert d["source"]["endpoint"] == "/mpp/stream/allTrades"


def test_strip_yaml_fence_fenced() -> None:
    raw = "```yaml\n" + _GOLDEN_YAML.strip() + "\n```"
    d = parse_llm_yaml_to_dict(raw)
    assert d["name"] == "test-create-agent"


def test_parse_llm_yaml_invalid() -> None:
    with pytest.raises(CreateError, match="not valid YAML"):
        parse_llm_yaml_to_dict("::: not yaml :::")


def test_parse_llm_yaml_not_mapping() -> None:
    with pytest.raises(CreateError, match="mapping"):
        parse_llm_yaml_to_dict("- a\n- b")


def test_validate_agent_dict_ok() -> None:
    d = parse_llm_yaml_to_dict(_GOLDEN_YAML)
    cfg = validate_agent_dict(d)
    assert isinstance(cfg, AgentConfig)
    assert cfg.name == "test-create-agent"


def test_validate_agent_dict_missing_name() -> None:
    d = parse_llm_yaml_to_dict(_GOLDEN_YAML)
    del d["name"]
    with pytest.raises(CreateError, match="Invalid agent"):
        validate_agent_dict(d)


def test_build_create_system_prompt_contains_schema_and_catalog(minimal_catalog: dict) -> None:
    s = build_create_system_prompt(minimal_catalog)
    assert "JSON Schema" in s or "properties" in s
    assert "min_usd" in s
    assert "stdout" in s
    assert catalog_endpoints_json_for_prompt(minimal_catalog) in s


def test_compile_nl_mock_backend(minimal_catalog: dict) -> None:
    class Fake:
        async def complete(self, system: str, user: str) -> str:
            assert "User request" in user or "swap" in user.lower()
            assert "JSON Schema" in system or "properties" in system
            return _GOLDEN_YAML

    async def run() -> None:
        cfg = await compile_nl_to_agent_config(
            "alert on big swaps",
            minimal_catalog,
            Fake(),
        )
        assert cfg.name == "test-create-agent"
        assert cfg.rules[0]["type"] == "min_usd"

    asyncio.run(run())


def test_default_output_filename() -> None:
    cfg = AgentConfig.model_validate(parse_llm_yaml_to_dict(_GOLDEN_YAML))
    assert default_output_filename(cfg) == "test-create-agent.yaml"
