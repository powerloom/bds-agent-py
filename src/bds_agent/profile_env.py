"""
Profile-backed defaults for BDS env vars (so you do not export a long list of variables).

Precedence for each logical setting: **explicit CLI** (where supported) → **process environment**
(non-empty) → **active profile JSON** keys → unset.

Profile file fields (optional, alongside ``api_key``):

- ``bds_base_url`` — same as ``BDS_BASE_URL``
- ``bds_api_endpoints_catalog_json`` — path to ``endpoints.json`` (``BDS_API_ENDPOINTS_CATALOG_JSON``)
- ``bds_sources_json`` — path to ``sources.json`` (``BDS_SOURCES_JSON``)
- ``bds_market_name`` — market name (``BDS_MARKET_NAME``)
"""

from __future__ import annotations

import os

from bds_agent.credentials import load_credentials

# Env names must match ``bds_agent.catalog`` and shell conventions.
_ENV_FROM_PROFILE_FIELD: dict[str, str] = {
    "BDS_BASE_URL": "bds_base_url",
    "BDS_API_ENDPOINTS_CATALOG_JSON": "bds_api_endpoints_catalog_json",
    "BDS_SOURCES_JSON": "bds_sources_json",
    "BDS_MARKET_NAME": "bds_market_name",
}


def get_profile_env_overlay() -> dict[str, str]:
    """Map env var name → value from the active profile JSON (non-empty strings only)."""
    creds = load_credentials()
    if not creds:
        return {}
    out: dict[str, str] = {}
    for env_name, field in _ENV_FROM_PROFILE_FIELD.items():
        v = creds.get(field)  # type: ignore[literal-required]
        if isinstance(v, str) and v.strip():
            out[env_name] = v.strip()
    return out


def env_or_profile(env_name: str) -> str:
    """
    Value for an env-style key: non-empty ``os.environ[env_name]`` wins, else profile overlay.
    """
    raw = os.environ.get(env_name, "")
    if raw.strip():
        return raw.strip()
    return get_profile_env_overlay().get(env_name, "").strip()


def resolve_bds_base_url(*, cli_override: str | None = None) -> str | None:
    """Snapshotter origin: CLI flag > env/profile > None."""
    if cli_override and str(cli_override).strip():
        return str(cli_override).strip().rstrip("/")
    v = env_or_profile("BDS_BASE_URL")
    return v.rstrip("/") if v else None
