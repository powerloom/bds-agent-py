from __future__ import annotations

import json
from pathlib import Path

import pytest

from bds_agent.catalog import (
    CatalogError,
    apply_agent_runtime_catalog_filter,
    filter_catalog_by_path_prefixes,
)


def test_filter_keeps_mpp_only() -> None:
    catalog = {
        "market": "X",
        "version": 1,
        "endpoints": [
            {"path": "/mpp/snapshot/allTrades", "method": "GET"},
            {"path": "/tradeVolume/{a}/{b}", "method": "GET"},
        ],
    }
    out = filter_catalog_by_path_prefixes(catalog, ("/mpp",))
    paths = [e["path"] for e in out["endpoints"]]
    assert paths == ["/mpp/snapshot/allTrades"]


def test_filter_prefix_no_false_positive() -> None:
    """``/mpp`` must not match ``/mppix/...``."""
    catalog = {
        "market": "X",
        "version": 1,
        "endpoints": [
            {"path": "/mppix/foo", "method": "GET"},
            {"path": "/mpp/stream/x", "method": "GET"},
        ],
    }
    out = filter_catalog_by_path_prefixes(catalog, ("/mpp",))
    paths = [e["path"] for e in out["endpoints"]]
    assert paths == ["/mpp/stream/x"]


def test_apply_agent_runtime_respects_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = Path(__file__).parent / "fixtures" / "endpoints.minimal.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    monkeypatch.delenv("BDS_AGENT_CATALOG_PATH_PREFIXES", raising=False)
    filtered = apply_agent_runtime_catalog_filter(catalog)
    assert len(filtered["endpoints"]) == 2

    monkeypatch.setenv("BDS_AGENT_CATALOG_PATH_PREFIXES", "all")
    assert apply_agent_runtime_catalog_filter(catalog) == catalog

    monkeypatch.setenv("BDS_AGENT_CATALOG_PATH_PREFIXES", "/tradeVolume")
    # minimal fixture has no /tradeVolume paths
    with pytest.raises(CatalogError, match="no endpoints"):
        apply_agent_runtime_catalog_filter(catalog)
