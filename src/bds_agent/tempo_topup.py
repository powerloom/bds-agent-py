from __future__ import annotations

import asyncio
import os
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from bds_agent.credentials import resolve_tempo_env_path
from bds_agent.plan_fields import (
    bundle_recipient_for_chain,
    bundle_rpc_for_chain,
    plan_chain_id,
    plan_token_amount,
    plan_token_contract,
    plan_token_decimals,
)
from bds_agent.paths import config_dir


def _merge_env_file(path: Path) -> None:
    """Merge KEY=val lines into os.environ (does not override existing)."""
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            continue
        k, v = s.split("=", 1)
        key = k.strip()
        val = v.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, val)


def load_tempo_env_file() -> None:
    """Merge per-profile `profiles/<name>.tempo.env` into os.environ (does not override existing)."""
    path = resolve_tempo_env_path()
    if path is not None:
        _merge_env_file(path)
        return
    legacy = config_dir() / "tempo.env"
    if legacy.is_file():
        _merge_env_file(legacy)


def human_to_atomic(amount: str, decimals: int) -> str:
    d = Decimal(amount)
    scale = Decimal(10) ** decimals
    return str(int(d * scale))


async def _json_rpc(rpc_url: str, method: str, params: list[Any]) -> Any:
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(
            rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )
        r.raise_for_status()
        j = r.json()
    err = j.get("error")
    if err:
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        raise RuntimeError(msg)
    return j.get("result")


async def _wait_for_receipt(rpc_url: str, tx_hash: str, timeout_sec: float = 120.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        rec = await _json_rpc(rpc_url, "eth_getTransactionReceipt", [tx_hash])
        if rec:
            return rec
        await asyncio.sleep(1.0)
    raise TimeoutError(f"Timed out waiting for receipt {tx_hash}")


async def execute_tempo_plan_payment(bundle: dict[str, Any], plan: dict[str, Any]) -> str:
    from datetime import datetime, timedelta, timezone

    from mpp import Challenge
    from mpp.methods.tempo import ChargeIntent, TempoAccount, tempo

    import mpp.methods.tempo.client as _mpp_tempo_client

    _mpp_tempo_client.DEFAULT_GAS_LIMIT = 1_000_000

    load_tempo_env_file()
    account = TempoAccount.from_env()
    chain_id = plan_chain_id(plan)
    rpc_url = (os.environ.get("TEMPO_RPC_URL") or os.environ.get("MPP_TEMPO_RPC_URL") or "").strip() or str(
        bundle_rpc_for_chain(bundle, chain_id),
    )
    if not rpc_url:
        raise ValueError(
            "Set TEMPO_RPC_URL or use the rpc_url for this chain from GET /credits/plans (chains[] or primary).",
        )

    t_dec = plan_token_decimals(plan)
    amount_atomic = human_to_atomic(plan_token_amount(plan), t_dec)

    method = tempo(
        account=account,
        chain_id=chain_id,
        rpc_url=rpc_url,
        intents={"charge": ChargeIntent()},
    )

    expires = (datetime.now(timezone.utc) + timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    ch = Challenge(
        id="bds-credit-topup",
        method="tempo",
        intent="charge",
        request={
            "amount": amount_atomic,
            "currency": plan_token_contract(plan),
            "recipient": (plan.get("recipient") or "").strip() or bundle_recipient_for_chain(bundle, chain_id),
            "methodDetails": {"chainId": chain_id},
        },
        realm="bds-agenthub",
        expires=expires,
    )

    try:
        cred = await method.create_credential(ch)
    finally:
        for intent in method.intents.values():
            if hasattr(intent, "aclose"):
                await intent.aclose()  # type: ignore[misc]

    payload = cred.payload
    if not isinstance(payload, dict) or payload.get("type") != "transaction":
        raise RuntimeError("Unexpected credential payload from pympp")
    raw_tx = str(payload.get("signature") or "")
    if not raw_tx.startswith("0x"):
        raise RuntimeError("Invalid raw transaction from pympp")

    result = await _json_rpc(rpc_url, "eth_sendRawTransaction", [raw_tx])
    if not result or not isinstance(result, str):
        raise RuntimeError("eth_sendRawTransaction returned no hash")
    tx_hash = result

    receipt = await _wait_for_receipt(rpc_url, tx_hash)
    status = receipt.get("status")
    if status != "0x1":
        raise RuntimeError(f"Transaction reverted (status={status})")

    return tx_hash


def run_tempo_topup_sync(bundle: dict[str, Any], plan: dict[str, Any]) -> str:
    return asyncio.run(execute_tempo_plan_payment(bundle, plan))
