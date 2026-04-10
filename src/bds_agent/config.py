"""
Load and validate ``agent.yaml``: env interpolation (``${VAR}``), Pydantic schema, API key resolution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from bds_agent.credentials import load_credentials
from bds_agent.paths import profiles_dir, sanitize_profile_name
from bds_agent.profile_env import env_or_profile

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(Exception):
    """Invalid ``agent.yaml``, missing env, or missing credentials."""


def interpolate_env(obj: Any) -> Any:
    """Replace ``${VAR}`` in strings using env first, then active profile BDS defaults."""
    if isinstance(obj, str):
        return _ENV_REF.sub(lambda m: env_or_profile(m.group(1)) or "", obj)
    if isinstance(obj, dict):
        return {k: interpolate_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [interpolate_env(v) for v in obj]
    return obj


def _apply_cli_profile_to_auth(data: dict[str, Any], profile_override: str | None) -> None:
    r"""
    ``bds-agent run --profile X`` must apply before Pydantic validation: otherwise
    ``profile: ${BDS_AGENT_PROFILE}`` with env unset becomes empty and validation fails.
    When there is no non-empty ``api_key``, set ``auth.profile`` from the CLI (overrides YAML).
    """
    if not profile_override or not str(profile_override).strip():
        return
    auth = data.get("auth")
    if not isinstance(auth, dict):
        return
    if (auth.get("api_key") or "").strip():
        return
    auth["profile"] = str(profile_override).strip()


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["bds_stream", "bds_fetch"]
    endpoint: str
    base_url: str


class AuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str | None = None
    profile: str | None = None


class LifecycleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reconnect: bool = True
    reconnect_delay: float = 5.0
    max_reconnects: int = 0


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: int = 1
    source: SourceConfig
    auth: AuthConfig
    rules: list[dict[str, Any]] = Field(default_factory=list)
    sinks: list[dict[str, Any]] = Field(default_factory=list)
    verify: bool = False
    lifecycle: LifecycleConfig | None = None

    @model_validator(mode="after")
    def auth_present(self) -> AgentConfig:
        a = self.auth
        if not (a.api_key or "").strip() and not (a.profile or "").strip():
            raise ValueError("auth requires api_key and/or profile")
        return self


@dataclass(frozen=True)
class ResolvedAgentConfig:
    """Validated YAML plus resolved Bearer token."""

    config: AgentConfig
    api_key: str


def load_agent_yaml(
    path: Path | str,
    *,
    profile_override: str | None = None,
) -> AgentConfig:
    """Read YAML, interpolate ``${VAR}``, apply optional CLI ``--profile``, validate."""
    p = Path(path)
    try:
        raw_text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"cannot read {p}: {e}") from e
    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as e:
        raise ConfigError(f"invalid YAML in {p}: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"agent config root must be a mapping, got {type(data).__name__}")
    interpolated = interpolate_env(data)
    _apply_cli_profile_to_auth(interpolated, profile_override)
    try:
        return AgentConfig.model_validate(interpolated)
    except Exception as e:
        raise ConfigError(f"invalid agent config: {e}") from e


def resolve_api_key(auth: AuthConfig, *, profile_override: str | None = None) -> str:
    """
    Bearer token for BDS requests.

    Precedence: non-empty ``auth.api_key`` → profile file for ``--profile`` (override) or
    ``auth.profile`` → error.
    """
    key = (auth.api_key or "").strip()
    if key:
        return key
    pname = (profile_override or auth.profile or "").strip()
    if not pname:
        raise ConfigError("auth requires api_key or profile (or pass --profile to run)")
    try:
        safe = sanitize_profile_name(pname)
    except ValueError as e:
        raise ConfigError(f"invalid profile name: {e}") from e
    creds = load_credentials(profiles_dir() / f"{safe}.json")
    if not creds or not creds.get("api_key"):
        raise ConfigError(f"no api_key in profile {safe!r} (run bds-agent signup)")
    return creds["api_key"]


def effective_lifecycle(cfg: AgentConfig) -> LifecycleConfig:
    return cfg.lifecycle or LifecycleConfig()


def load_resolved_agent_config(
    path: Path | str,
    *,
    profile_override: str | None = None,
) -> ResolvedAgentConfig:
    """Load ``agent.yaml`` and resolve API key from inline key or profile."""
    cfg = load_agent_yaml(path, profile_override=profile_override)
    api_key = resolve_api_key(cfg.auth, profile_override=profile_override)
    return ResolvedAgentConfig(config=cfg, api_key=api_key)
