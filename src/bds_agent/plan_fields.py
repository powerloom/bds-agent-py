"""Field names for GET /credits/plans and POST /credits/topup (canonical only)."""

from __future__ import annotations

from typing import Any


def bundle_primary_recipient(data: dict[str, Any]) -> str:
    return str(data.get("primary_recipient") or "").strip()


def bundle_primary_chain_id(data: dict[str, Any]) -> Any:
    return data.get("primary_chain_id")


def bundle_primary_rpc_url(data: dict[str, Any]) -> str:
    return str(data.get("primary_rpc_url") or "").strip()


def plan_chain_id(plan: dict[str, Any]) -> int:
    cid = plan.get("chain_id")
    if cid is not None:
        return int(cid)
    raise ValueError("plan has no chain_id")


def plan_token_amount(plan: dict[str, Any]) -> str:
    return str(plan.get("token_amount") or "")


def plan_token_decimals(plan: dict[str, Any]) -> int:
    d = plan.get("token_decimals")
    if d is not None:
        return int(d)
    return 6


def plan_token_contract(plan: dict[str, Any]) -> str:
    return str(plan.get("token_contract") or "")


def bundle_recipient_for_chain(bundle: dict[str, Any], chain_id: int) -> str:
    for ch in bundle.get("chains") or []:
        if not isinstance(ch, dict):
            continue
        if int(ch.get("chain_id", -1)) != chain_id:
            continue
        r = str(ch.get("recipient") or "").strip()
        if r:
            return r
    return bundle_primary_recipient(bundle)


def bundle_rpc_for_chain(bundle: dict[str, Any], chain_id: int) -> str:
    for ch in bundle.get("chains") or []:
        if not isinstance(ch, dict):
            continue
        if int(ch.get("chain_id", -1)) != chain_id:
            continue
        u = str(ch.get("rpc_url") or "").strip()
        if u:
            return u
    return bundle_primary_rpc_url(bundle)
