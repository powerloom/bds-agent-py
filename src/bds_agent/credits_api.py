from __future__ import annotations

from typing import Any

import httpx


class CreditsError(Exception):
    pass


def credits_plans(base_url: str) -> dict[str, Any]:
    """GET /credits/plans (public)."""
    base = base_url.rstrip("/")
    with httpx.Client(timeout=30.0) as client:
        r = client.get(f"{base}/credits/plans")
    if r.status_code != 200:
        try:
            detail = r.json()
        except Exception:
            detail = r.text
        raise CreditsError(f"plans failed ({r.status_code}): {detail}")
    data = r.json()
    if not isinstance(data, dict):
        raise CreditsError("Invalid JSON from credits/plans")
    return data


def credits_balance(base_url: str, api_key: str) -> dict[str, Any]:
    base = base_url.rstrip("/")
    with httpx.Client(timeout=30.0) as client:
        r = client.get(
            f"{base}/credits/balance",
            headers={"Authorization": f"Bearer {api_key}"},
        )
    if r.status_code == 401:
        raise CreditsError("Unauthorized — check your API key in the credentials file.")
    if r.status_code != 200:
        try:
            detail = r.json()
        except Exception:
            detail = r.text
        raise CreditsError(f"balance failed ({r.status_code}): {detail}")
    data = r.json()
    if not isinstance(data, dict):
        raise CreditsError("Invalid JSON from credits/balance")
    return data


def credits_topup(
    base_url: str,
    api_key: str,
    *,
    amount: float | None = None,
    dev_secret: str | None = None,
) -> tuple[dict[str, Any] | None, int]:
    """POST /credits/topup. Returns (parsed_json_or_none, status_code)."""
    base = base_url.rstrip("/")
    headers: dict[str, str] = {"Authorization": f"Bearer {api_key}"}
    body: dict[str, Any] = {}
    if amount is not None and dev_secret:
        body["amount"] = amount
        headers["X-BDS-Dev-Topup-Secret"] = dev_secret

    with httpx.Client(timeout=30.0) as client:
        r = client.post(f"{base}/credits/topup", json=body, headers=headers)

    try:
        data = r.json()
    except Exception:
        data = None
    if isinstance(data, dict):
        return data, r.status_code
    return None, r.status_code


def credits_topup_onchain(
    base_url: str,
    api_key: str,
    *,
    plan_id: str,
    tx_hash: str,
    chain_id: int,
) -> tuple[dict[str, Any] | None, int]:
    """POST /credits/topup after a confirmed on-chain token transfer."""
    base = base_url.rstrip("/")
    body: dict[str, Any] = {
        "plan_id": plan_id,
        "tx_hash": tx_hash,
        "chain_id": chain_id,
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(timeout=60.0) as client:
        r = client.post(f"{base}/credits/topup", json=body, headers=headers)
    try:
        data = r.json()
    except Exception:
        data = None
    if isinstance(data, dict):
        return data, r.status_code
    return None, r.status_code
