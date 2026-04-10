from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from bds_agent.catalog import CatalogError, load_catalog_ref


def test_load_catalog_ref_local_file(tmp_path: Path) -> None:
    p = tmp_path / "endpoints.json"
    sample = {"market": "M", "version": 1, "endpoints": []}
    p.write_text(json.dumps(sample), encoding="utf-8")
    assert load_catalog_ref(str(p)) == sample


def test_load_catalog_ref_https() -> None:
    sample = {"market": "M", "version": 1, "endpoints": []}

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith("https://example.com/")
        return httpx.Response(200, json=sample)

    transport = httpx.MockTransport(handler)
    inner = httpx.Client(transport=transport, timeout=60.0)

    class _CM:
        def __enter__(self) -> httpx.Client:
            return inner

        def __exit__(self, *a: object) -> None:
            inner.close()

    with patch("bds_agent.catalog.httpx.Client", lambda **kw: _CM()):
        assert load_catalog_ref("https://example.com/api/endpoints.json") == sample


def test_load_catalog_ref_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="nope")

    transport = httpx.MockTransport(handler)
    inner = httpx.Client(transport=transport, timeout=60.0)

    class _CM:
        def __enter__(self) -> httpx.Client:
            return inner

        def __exit__(self, *a: object) -> None:
            inner.close()

    with patch("bds_agent.catalog.httpx.Client", lambda **kw: _CM()):
        with pytest.raises(CatalogError):
            load_catalog_ref("https://example.com/missing.json")
