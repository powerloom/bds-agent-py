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
    bds_base_url: str
    bds_api_endpoints_catalog_json: str
    bds_sources_json: str
    bds_market_name: str


# Optional fields merged on save so signup does not wipe operator defaults.
OPTIONAL_PROFILE_BDS_KEYS: tuple[str, ...] = (
    "bds_base_url",
    "bds_api_endpoints_catalog_json",
    "bds_sources_json",
    "bds_market_name",
)


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
    for k in OPTIONAL_PROFILE_BDS_KEYS:
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
    existing: dict[str, Any] = {}
    if p.is_file():
        try:
            prev = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(prev, dict):
                existing = prev
        except (OSError, json.JSONDecodeError):
            pass

    payload: dict[str, Any] = {
        "api_key": creds["api_key"],
        "org_id": creds.get("org_id", ""),
        "signup_base_url": creds.get("signup_base_url", ""),
    }
    if creds.get("profile_name"):
        payload["profile_name"] = creds["profile_name"]
    for k in OPTIONAL_PROFILE_BDS_KEYS:
        if k in creds and isinstance(creds.get(k), str) and str(creds[k]).strip():
            payload[k] = str(creds[k]).strip()
        elif k in existing and isinstance(existing.get(k), str) and str(existing[k]).strip():
            payload[k] = str(existing[k]).strip()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)
    try:
        os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return p


def update_profile_bds_fields(
    updates: dict[str, str | None],
    *,
    profile_name: str | None = None,
) -> Path:
    """
    Set or remove optional BDS keys on a profile JSON file.

    ``updates`` values: non-empty string to set, ``None`` or empty string to remove the key.
    Keys must be in :data:`OPTIONAL_PROFILE_BDS_KEYS`.
    """
    if profile_name and str(profile_name).strip():
        p = profiles_dir() / f"{sanitize_profile_name(str(profile_name).strip())}.json"
    else:
        p = resolve_credentials_path()
    if p is None or not p.is_file():
        raise ValueError(
            "No profile selected or profile file missing (use --profile / BDS_AGENT_PROFILE or signup).",
        )
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"Cannot read profile {p}: {e}") from e
    if not isinstance(raw, dict):
        raise ValueError("Profile JSON must be an object")
    data: dict[str, Any] = dict(raw)
    for k, v in updates.items():
        if k not in OPTIONAL_PROFILE_BDS_KEYS:
            raise ValueError(
                f"Unknown key {k!r}; allowed: {', '.join(OPTIONAL_PROFILE_BDS_KEYS)}",
            )
        if v is None:
            data.pop(k, None)
        else:
            s = str(v).strip()
            if not s:
                data.pop(k, None)
            else:
                data[k] = s
    if "api_key" not in data or not str(data.get("api_key", "")).strip():
        raise ValueError("Refusing to write profile without api_key")
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)
    try:
        os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return p
