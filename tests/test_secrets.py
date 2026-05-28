"""Secret redaction for operator-facing errors."""

from __future__ import annotations

from bds_agent.secrets import redact_secrets


def test_redact_private_key() -> None:
    key = "0x" + "a" * 64
    assert key not in redact_secrets(f"failed with {key}")


def test_redact_api_key() -> None:
    sk = "sk_live_" + "x" * 40
    assert sk not in redact_secrets(f"auth {sk}")
