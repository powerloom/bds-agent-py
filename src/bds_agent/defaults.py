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

# Powerloom chain JSON-RPC (``bds-agent run`` verification: ``verify: true`` → profile / ``POWERLOOM_RPC_URL``).
DEFAULT_POWERLOOM_RPC_URL = "https://rpc-v2.powerloom.network/"

# BDS mainnet alpha Uniswap V3 ETH deployment (matches snapshotter ``PROTOCOL_STATE_CONTRACT`` / ``DATA_MARKET_CONTRACT``).
DEFAULT_POWERLOOM_PROTOCOL_STATE = "0xa1100CB00Acd3cA83a7C8F4DAA42701D1Eaf4A6c"
DEFAULT_POWERLOOM_DATA_MARKET = "0x4198Bf81B55EE4Af6f9Ddc176F8021960813f641"
