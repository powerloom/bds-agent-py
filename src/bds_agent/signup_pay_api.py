from __future__ import annotations

from typing import Any

import httpx


class SignupPayError(Exception):
    """Pay-signup (quote/claim) failed."""


def signup_pay_quote(
    client: httpx.Client,
    base_url: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    base = base_url.rstrip("/")
    r = client.post(f"{base}/signup/pay/quote", json=payload, timeout=60.0)
    try:
        data = r.json() if r.content else {}
    except Exception:
        data = {"detail": r.text}
    if not isinstance(data, dict):
        data = {"detail": str(data)}
    return data, r.status_code


def signup_pay_claim(
    client: httpx.Client,
    base_url: str,
    signup_nonce: str,
    tx_hash: str,
) -> tuple[dict[str, Any], int]:
    base = base_url.rstrip("/")
    r = client.post(
        f"{base}/signup/pay/claim",
        json={"signup_nonce": signup_nonce, "tx_hash": tx_hash},
        timeout=120.0,
    )
    try:
        data = r.json() if r.content else {}
    except Exception:
        data = {"detail": r.text}
    if not isinstance(data, dict):
        data = {"detail": str(data)}
    return data, r.status_code
