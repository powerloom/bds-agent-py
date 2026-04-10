"""
Load the BDS endpoint catalog (`endpoints.json`) from disk or via curated-datamarkets discovery.

The catalog is authored next to `computes/api/router.py` in the snapshotter-computes repo.
Consumers resolve: ``sources.json`` → ``compute.commit`` → raw GitHub file at pinned commit.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import httpx

from bds_agent.paths import config_dir
from bds_agent.profile_env import env_or_profile

# Path inside the snapshotter-computes repo root (``api/router.py`` → ``api/endpoints.json``).
# In snapshotter-core-edge this subtree is mounted as ``computes/api/``.
CATALOG_RELATIVE_PATH = "api/endpoints.json"

ENV_API_ENDPOINTS_CATALOG_JSON = "BDS_API_ENDPOINTS_CATALOG_JSON"
ENV_SOURCES_JSON = "BDS_SOURCES_JSON"
ENV_MARKET = "BDS_MARKET_NAME"
DEFAULT_MARKET = "BDS_MAINNET_UNISWAPV3"


class CatalogError(Exception):
    """Invalid catalog JSON, missing market entry, or fetch failure."""


_GITHUB_REPO_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$",
    re.I,
)


def _parse_github_repo_url(url: str) -> tuple[str, str]:
    m = _GITHUB_REPO_RE.match(url.strip())
    if not m:
        raise CatalogError(f"Cannot parse GitHub repo URL: {url!r}")
    owner, repo = m.group(1), m.group(2)
    return owner, repo


def raw_github_url(owner: str, repo: str, commit: str, path_in_repo: str) -> str:
    """HTTPS URL for a file at a pinned commit (raw.githubusercontent.com)."""
    path_in_repo = path_in_repo.lstrip("/")
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{commit}/{path_in_repo}"


def _validate_catalog(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise CatalogError("Catalog root must be a JSON object")
    for key in ("market", "version", "endpoints"):
        if key not in data:
            raise CatalogError(f"Catalog missing required key: {key!r}")
    if not isinstance(data["endpoints"], list):
        raise CatalogError("Catalog 'endpoints' must be an array")
    return data


def _is_http_url(ref: str) -> bool:
    s = ref.strip().lower()
    return s.startswith("http://") or s.startswith("https://")


def load_catalog_file(path: Path) -> dict[str, Any]:
    """Read and minimally validate ``endpoints.json`` from a local path."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise CatalogError(f"Cannot read catalog file {path}: {e}") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise CatalogError(f"Invalid JSON in {path}: {e}") from e
    return _validate_catalog(data)


def load_catalog_ref(ref: str) -> dict[str, Any]:
    """
    Load ``endpoints.json`` from a **local path** or **HTTPS URL** (e.g. raw GitHub).

    ``BDS_API_ENDPOINTS_CATALOG_JSON`` / profile ``bds_api_endpoints_catalog_json`` may be either.
    """
    s = ref.strip()
    if not s:
        raise CatalogError("Catalog reference is empty")
    if _is_http_url(s):
        headers: dict[str, str] = {}
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                r = client.get(s, headers=headers)
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as e:
            raise CatalogError(f"Failed to fetch catalog from {s}: {e}") from e
        except json.JSONDecodeError as e:
            raise CatalogError(f"Response is not valid JSON: {s}: {e}") from e
        return _validate_catalog(data)
    return load_catalog_file(Path(s).expanduser())


def _find_market_entry(sources: Any, market_name: str) -> dict[str, Any]:
    if not isinstance(sources, list):
        raise CatalogError("sources.json root must be a JSON array")
    for chain_entry in sources:
        if not isinstance(chain_entry, dict):
            continue
        markets = chain_entry.get("dataMarkets")
        if not isinstance(markets, list):
            continue
        for m in markets:
            if isinstance(m, dict) and m.get("name") == market_name:
                return m
    raise CatalogError(f"No data market named {market_name!r} in sources.json")


def _compute_spec_from_market(market: dict[str, Any]) -> tuple[str, str, str]:
    compute = market.get("compute")
    if not isinstance(compute, dict):
        raise CatalogError("Market entry has no 'compute' object")
    repo_url = compute.get("repo")
    commit = compute.get("commit")
    if not repo_url or not commit:
        raise CatalogError("Market 'compute' must include 'repo' and 'commit'")
    if not isinstance(repo_url, str) or not isinstance(commit, str):
        raise CatalogError("'repo' and 'commit' must be strings")
    owner, repo = _parse_github_repo_url(repo_url)
    return owner, repo, commit


def _cache_path_for_commit(commit: str) -> Path:
    safe = re.sub(r"[^a-fA-F0-9]", "", commit)[:40]
    return config_dir() / "cache" / f"endpoints_{safe}.json"


def fetch_catalog_from_github(
    owner: str,
    repo: str,
    commit: str,
    *,
    path_in_repo: str = CATALOG_RELATIVE_PATH,
    timeout_s: float = 60.0,
) -> dict[str, Any]:
    """GET the catalog JSON from raw.githubusercontent.com at a pinned commit."""
    url = raw_github_url(owner, repo, commit, path_in_repo)
    headers: dict[str, str] = {}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
            r = client.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        raise CatalogError(f"Failed to fetch catalog from {url}: {e}") from e
    except json.JSONDecodeError as e:
        raise CatalogError(f"Response is not valid JSON: {url}: {e}") from e
    return _validate_catalog(data)


def load_catalog_from_sources_file(
    sources_path: Path,
    *,
    market_name: str | None = None,
    use_cache: bool = True,
    path_in_repo: str = CATALOG_RELATIVE_PATH,
) -> dict[str, Any]:
    """
    Read ``sources.json``, find the named data market, and load ``endpoints.json``
    from GitHub at ``compute.commit``. Caches under ``~/.config/bds-agent/cache/``.
    """
    name = market_name or env_or_profile(ENV_MARKET) or DEFAULT_MARKET
    try:
        raw = sources_path.read_text(encoding="utf-8")
    except OSError as e:
        raise CatalogError(f"Cannot read sources file {sources_path}: {e}") from e
    try:
        sources = json.loads(raw)
    except json.JSONDecodeError as e:
        raise CatalogError(f"Invalid JSON in {sources_path}: {e}") from e
    market = _find_market_entry(sources, name)
    owner, repo, commit = _compute_spec_from_market(market)

    cache_file = _cache_path_for_commit(commit)
    if use_cache and cache_file.is_file():
        try:
            return load_catalog_file(cache_file)
        except CatalogError:
            pass

    data = fetch_catalog_from_github(owner, repo, commit, path_in_repo=path_in_repo)
    if use_cache:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass
    return data


def resolve_catalog(
    *,
    endpoints_path: Path | None = None,
    sources_path: Path | None = None,
    market_name: str | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """
    Resolve the catalog in order:

    1. ``endpoints_path`` if provided
    2. :envvar:`BDS_API_ENDPOINTS_CATALOG_JSON` if set (non-empty), else the same key from the **active profile** JSON
    3. ``sources_path`` if provided → GitHub fetch at pinned commit
    4. :envvar:`BDS_SOURCES_JSON` if set, else profile

    Raises :exc:`CatalogError` if nothing resolves or validation fails.
    """
    if endpoints_path is not None:
        return load_catalog_ref(str(endpoints_path))

    env_ep = env_or_profile(ENV_API_ENDPOINTS_CATALOG_JSON)
    if env_ep:
        return load_catalog_ref(env_ep)

    src = sources_path
    if src is None:
        env_src = env_or_profile(ENV_SOURCES_JSON)
        if env_src:
            src = Path(env_src).expanduser()

    if src is not None:
        return load_catalog_from_sources_file(
            Path(src),
            market_name=market_name,
            use_cache=use_cache,
        )

    raise CatalogError(
        "No catalog source: set BDS_API_ENDPOINTS_CATALOG_JSON to a local endpoints.json, "
        "or BDS_SOURCES_JSON to curated-datamarkets/sources.json, "
        "or add bds_api_endpoints_catalog_json / bds_sources_json to the active profile JSON ("
        "or pass endpoints_path= / sources_path= to resolve_catalog())",
    )


def catalog_endpoint_paths(catalog: dict[str, Any]) -> set[str]:
    """Set of route path templates from a loaded catalog."""
    eps = catalog.get("endpoints")
    if not isinstance(eps, list):
        return set()
    out: set[str] = set()
    for e in eps:
        if isinstance(e, dict) and isinstance(e.get("path"), str):
            out.add(e["path"])
    return out


# Env: comma-separated path prefixes; default metered agent surface is ``/mpp`` only.
ENV_AGENT_CATALOG_PATH_PREFIXES = "BDS_AGENT_CATALOG_PATH_PREFIXES"


def agent_runtime_path_prefixes() -> tuple[str, ...] | None:
    """
    Path prefixes allowed for **agent** surfaces (``query``, MCP tools, ``run`` validation).

    - **Unset:** ``("/mpp",)`` — only routes under ``/mpp/...`` (metered BDS API surface).
    - Set to ``*`` or ``all`` (case-insensitive): **no** filtering (full catalog; operator risk).
    - Otherwise: comma-separated prefixes, e.g. ``/mpp,/custom``.
    """
    raw = os.environ.get(ENV_AGENT_CATALOG_PATH_PREFIXES, "")
    if not raw.strip():
        return ("/mpp",)
    s = raw.strip().lower()
    if s in ("*", "all"):
        return None
    parts = tuple(p.strip().rstrip("/") for p in raw.split(",") if p.strip())
    if not parts:
        return ("/mpp",)
    # Normalize: "/mpp" matches "/mpp/stream/..."
    return tuple(p if p.startswith("/") else f"/{p}" for p in parts)


def filter_catalog_by_path_prefixes(
    catalog: dict[str, Any],
    prefixes: tuple[str, ...],
) -> dict[str, Any]:
    """Return a shallow copy of ``catalog`` with ``endpoints`` restricted to matching path prefixes."""
    eps = catalog.get("endpoints")
    if not isinstance(eps, list):
        return dict(catalog)
    kept: list[dict[str, Any]] = []
    for e in eps:
        if not isinstance(e, dict):
            continue
        p = e.get("path")
        if not isinstance(p, str):
            continue
        if any(
            p == prefix or p.startswith(prefix + "/")
            for prefix in prefixes
        ):
            kept.append(e)
    out = dict(catalog)
    out["endpoints"] = kept
    return out


def apply_agent_runtime_catalog_filter(catalog: dict[str, Any]) -> dict[str, Any]:
    """
    Apply :func:`agent_runtime_path_prefixes` to the catalog.

    Raises :exc:`CatalogError` if filtering removes every endpoint.
    """
    prefs = agent_runtime_path_prefixes()
    if prefs is None:
        return catalog
    filtered = filter_catalog_by_path_prefixes(catalog, prefs)
    eps = filtered.get("endpoints")
    if not isinstance(eps, list) or not eps:
        raise CatalogError(
            "After BDS_AGENT_CATALOG_PATH_PREFIXES filtering, the catalog has no endpoints. "
            f"Prefixes: {prefs!r}. Check endpoints.json or set {ENV_AGENT_CATALOG_PATH_PREFIXES}=all.",
        )
    return filtered
