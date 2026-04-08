from __future__ import annotations

import json
import os
import stat
from contextvars import ContextVar
from pathlib import Path
from typing import Any, TypedDict

from bds_agent.paths import (
    active_profile_path,
    profiles_dir,
    sanitize_profile_name,
    tempo_env_path_for_profile,
)

_cli_profile: ContextVar[str | None] = ContextVar("cli_profile", default=None)


def set_cli_profile(name: str | None) -> None:
    """Set by Typer root callback from --profile / BDS_AGENT_PROFILE."""
    if name is None:
        _cli_profile.set(None)
        return
    s = str(name).strip()
    _cli_profile.set(s or None)


class Credentials(TypedDict, total=False):
    api_key: str
    org_id: str
    signup_base_url: str
    profile_name: str


def read_active_profile_name() -> str | None:
    p = active_profile_path()
    if not p.is_file():
        return None
    try:
        line = p.read_text(encoding="utf-8").strip().splitlines()
        if not line:
            return None
        return sanitize_profile_name(line[0])
    except (OSError, ValueError):
        return None


def write_active_profile_name(name: str) -> None:
    n = sanitize_profile_name(name)
    p = active_profile_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(n + "\n", encoding="utf-8")
    try:
        os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def resolve_credentials_path() -> Path | None:
    """Path to `profiles/<name>.json`, or None if no profile is selected."""
    explicit = _cli_profile.get()
    if explicit and explicit.strip():
        return profiles_dir() / f"{sanitize_profile_name(explicit.strip())}.json"
    env_p = os.environ.get("BDS_AGENT_PROFILE", "").strip()
    if env_p:
        return profiles_dir() / f"{sanitize_profile_name(env_p)}.json"
    active = read_active_profile_name()
    if active:
        return profiles_dir() / f"{sanitize_profile_name(active)}.json"
    return None


def resolve_profile_name() -> str | None:
    """Same profile selection as credentials file: CLI, env, then active_profile."""
    explicit = _cli_profile.get()
    if explicit and explicit.strip():
        return sanitize_profile_name(explicit.strip())
    env_p = os.environ.get("BDS_AGENT_PROFILE", "").strip()
    if env_p:
        return sanitize_profile_name(env_p)
    return read_active_profile_name()


def resolve_tempo_env_path() -> Path | None:
    """Per-profile Tempo file: profiles/<name>.tempo.env; None if no profile is selected."""
    n = resolve_profile_name()
    if not n:
        return None
    return tempo_env_path_for_profile(n)


def describe_credentials_location() -> str:
    """Human-readable path or hint when nothing is configured yet."""
    p = resolve_credentials_path()
    if p is not None:
        return str(p)
    return (
        f"{profiles_dir()}/<profile>.json "
        f"(create via `bds-agent signup`, or set {active_profile_path().name} / --profile / BDS_AGENT_PROFILE)"
    )


def _load_from_file(p: Path) -> Credentials | None:
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    out: Credentials = {}
    for k in ("api_key", "org_id", "signup_base_url", "profile_name"):
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()  # type: ignore[literal-required]
    return out if "api_key" in out else None


def load_credentials(path: Path | None = None) -> Credentials | None:
    if path is not None:
        return _load_from_file(path)
    resolved = resolve_credentials_path()
    if resolved is None:
        return None
    return _load_from_file(resolved)


def save_credentials(
    creds: Credentials,
    path: Path | None = None,
    *,
    profile_name: str | None = None,
) -> Path:
    """Write credentials. Use profile_name to save under profiles/ and set active profile."""
    if path is not None:
        p = path
    elif profile_name is not None:
        n = sanitize_profile_name(profile_name)
        profiles_dir().mkdir(parents=True, exist_ok=True)
        p = profiles_dir() / f"{n}.json"
        creds = {**creds, "profile_name": n}
        write_active_profile_name(n)
    else:
        raise ValueError("save_credentials requires profile_name or path")

    p.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "api_key": creds["api_key"],
        "org_id": creds.get("org_id", ""),
        "signup_base_url": creds.get("signup_base_url", ""),
    }
    if creds.get("profile_name"):
        payload["profile_name"] = creds["profile_name"]
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)
    try:
        os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return p
