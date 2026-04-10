from __future__ import annotations

import json
from pathlib import Path

import pytest

from bds_agent.config import (
    interpolate_env,
    load_agent_yaml,
    load_resolved_agent_config,
    resolve_api_key,
)
from bds_agent.credentials import save_credentials


def test_interpolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BDS_AGENT_TEST_VAR", raising=False)
    assert interpolate_env("x${BDS_AGENT_TEST_VAR}y") == "xy"
    monkeypatch.setenv("BDS_AGENT_TEST_VAR", "bar")
    assert interpolate_env("x${BDS_AGENT_TEST_VAR}y") == "xbary"


def test_load_minimal_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "a.yaml"
    p.write_text(
        """
name: test
source:
  type: bds_stream
  endpoint: /mpp/stream/allTrades
  base_url: http://127.0.0.1:9003
auth:
  api_key: sk_test_123
rules: []
sinks:
  - type: stdout
""",
        encoding="utf-8",
    )
    cfg = load_agent_yaml(p)
    assert cfg.name == "test"
    assert cfg.source.type == "bds_stream"
    assert cfg.rules == []
    assert cfg.sinks == [{"type": "stdout"}]


def test_resolve_from_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    profiles = tmp_path / ".config" / "bds-agent" / "profiles"
    profiles.mkdir(parents=True)
    save_credentials(
        {"api_key": "sk_from_profile", "org_id": "o", "signup_base_url": "http://x"},
        profile_name="p1",
    )
    cfg_path = tmp_path / "agent.yaml"
    cfg_path.write_text(
        """
name: x
source:
  type: bds_stream
  endpoint: /mpp/stream/allTrades
  base_url: http://127.0.0.1:9003
auth:
  profile: p1
rules: []
sinks: []
""",
        encoding="utf-8",
    )
    cfg = load_agent_yaml(cfg_path)
    assert resolve_api_key(cfg.auth) == "sk_from_profile"


def test_cli_profile_applied_before_validate(tmp_path: Path) -> None:
    """``--profile`` must work when YAML only has profile: ``${BDS_AGENT_PROFILE}`` and env is unset."""
    cfg_path = tmp_path / "agent.yaml"
    cfg_path.write_text(
        """
name: x
source:
  type: bds_stream
  endpoint: /mpp/stream/allTrades
  base_url: http://127.0.0.1:9003
auth:
  profile: ${BDS_AGENT_PROFILE}
rules: []
sinks: []
""",
        encoding="utf-8",
    )
    cfg = load_agent_yaml(cfg_path, profile_override="bds-test1")
    assert cfg.auth.profile == "bds-test1"


def test_profile_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    profiles = tmp_path / ".config" / "bds-agent" / "profiles"
    profiles.mkdir(parents=True)
    (profiles / "p1.json").write_text(
        json.dumps({"api_key": "k1", "org_id": "", "signup_base_url": ""}),
        encoding="utf-8",
    )
    (profiles / "p2.json").write_text(
        json.dumps({"api_key": "k2", "org_id": "", "signup_base_url": ""}),
        encoding="utf-8",
    )
    cfg_path = tmp_path / "agent.yaml"
    cfg_path.write_text(
        """
name: x
source:
  type: bds_stream
  endpoint: /mpp/stream/allTrades
  base_url: http://127.0.0.1:9003
auth:
  profile: p1
rules: []
sinks: []
""",
        encoding="utf-8",
    )
    r = load_resolved_agent_config(cfg_path, profile_override="p2")
    assert r.api_key == "k2"
