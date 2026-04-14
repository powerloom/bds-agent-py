"""Packaged defaults for ``bds-agent config init`` (BDS + Powerloom verification)."""

from __future__ import annotations

from bds_agent import defaults


def test_powerloom_verification_defaults_mainnet_alpha() -> None:
    assert defaults.DEFAULT_POWERLOOM_RPC_URL == "https://rpc-v2.powerloom.network/"
    assert defaults.DEFAULT_POWERLOOM_PROTOCOL_STATE == (
        "0xa1100CB00Acd3cA83a7C8F4DAA42701D1Eaf4A6c"
    )
    assert defaults.DEFAULT_POWERLOOM_DATA_MARKET == (
        "0x4198Bf81B55EE4Af6f9Ddc176F8021960813f641"
    )
