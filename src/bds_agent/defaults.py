"""
Public defaults for first-time profile setup (`bds-agent config init`).

These are starting points; override with ``bds-agent config set`` or env vars when needed.
"""

from __future__ import annotations

# Snapshotter HTTP API origin (public deployment uses ``/api`` prefix) — no trailing slash.
DEFAULT_BDS_BASE_URL = "https://bds.powerloom.io/api"

# Pinned branch copy of ``api/endpoints.json`` from snapshotter-computes (BDS Uniswap V3 market).
DEFAULT_ENDPOINTS_CATALOG_URL = (
    "https://raw.githubusercontent.com/powerloom/snapshotter-computes/"
    "refs/heads/bds_eth_uniswapv3_core/api/endpoints.json"
)
