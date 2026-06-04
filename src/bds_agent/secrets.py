"""Redact credentials from logs and error messages."""

from __future__ import annotations

import re

_HEX_KEY = re.compile(r"\b0x[0-9a-fA-F]{64}\b")
_SK_LIVE = re.compile(r"\bsk_live_[0-9a-zA-Z]+\b")
_SK_TEST = re.compile(r"\bsk_test_[0-9a-zA-Z]+\b")


def redact_secrets(text: str) -> str:
    """Mask private keys and API keys before printing or persisting."""
    if not text:
        return text
    out = _HEX_KEY.sub("0x<redacted>", text)
    out = _SK_LIVE.sub("sk_live_<redacted>", out)
    out = _SK_TEST.sub("sk_test_<redacted>", out)
    return out


def install_safe_traceback() -> None:
    """Disable Rich locals in tracebacks (prevents EVM/BDS secrets in stack dumps)."""
    try:
        from rich.traceback import install

        install(show_locals=False, suppress=[])
    except Exception:
        pass
