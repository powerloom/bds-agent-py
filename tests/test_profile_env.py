from __future__ import annotations

import json
from pathlib import Path

import pytest

from bds_agent.config import load_agent_yaml
from bds_agent.profile_env import env_or_profile, resolve_bds_base_url


def test_env_wins_over_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_dir = tmp_path / ".config" / "bds-agent"
    profiles = cfg_dir / "profiles"
    profiles.mkdir(parents=True)
    (profiles / "p1.json").write_text(
        json.dumps(
            {
                "api_key": "sk",
                "org_id": "",
                "signup_base_url": "",
                "bds_base_url": "http://from-profile",
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BDS_AGENT_PROFILE", "p1")
    monkeypatch.setenv("BDS_BASE_URL", "http://from-env")
    assert env_or_profile("BDS_BASE_URL") == "http://from-env"


def test_profile_fallback_for_base_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    profiles = tmp_path / ".config" / "bds-agent" / "profiles"
    profiles.mkdir(parents=True)
    (profiles / "p1.json").write_text(
        json.dumps(
            {
                "api_key": "sk",
                "org_id": "",
                "signup_base_url": "",
                "bds_base_url": "http://node.example",
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BDS_AGENT_PROFILE", "p1")
    monkeypatch.delenv("BDS_BASE_URL", raising=False)
    assert resolve_bds_base_url(cli_override=None) == "http://node.example"


def test_agent_yaml_interpolates_base_url_from_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    profiles = tmp_path / ".config" / "bds-agent" / "profiles"
    profiles.mkdir(parents=True)
    (profiles / "p1.json").write_text(
        json.dumps(
            {
                "api_key": "sk",
                "org_id": "",
                "signup_base_url": "",
                "bds_base_url": "http://interp.example",
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BDS_AGENT_PROFILE", "p1")
    monkeypatch.delenv("BDS_BASE_URL", raising=False)
    p = tmp_path / "a.yaml"
    p.write_text(
        """
name: t
source:
  type: bds_stream
  endpoint: /mpp/stream/allTrades
  base_url: ${BDS_BASE_URL}
auth:
  profile: p1
rules: []
sinks: []
""",
        encoding="utf-8",
    )
    cfg = load_agent_yaml(p)
    assert cfg.source.base_url == "http://interp.example"


def test_profile_sources_json_without_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    profiles = tmp_path / ".config" / "bds-agent" / "profiles"
    profiles.mkdir(parents=True)
    (profiles / "p1.json").write_text(
        json.dumps(
            {
                "api_key": "sk",
                "org_id": "",
                "signup_base_url": "",
                "bds_sources_json": "/path/to/sources.json",
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BDS_AGENT_PROFILE", "p1")
    monkeypatch.delenv("BDS_SOURCES_JSON", raising=False)
    assert env_or_profile("BDS_SOURCES_JSON") == "/path/to/sources.json"
