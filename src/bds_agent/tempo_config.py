"""Interactive / file-based Tempo wallet config for credit purchases only."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from bds_agent.credentials import resolve_tempo_env_path
from bds_agent.plan_fields import (
    bundle_primary_chain_id,
    bundle_primary_recipient,
    bundle_primary_rpc_url,
    plan_token_amount,
)


def write_tempo_env_file(
    private_key: str,
    *,
    rpc_url: str | None = None,
    chain_id: str | None = None,
    path: Path | None = None,
) -> Path:
    """Write per-profile `profiles/<name>.tempo.env` with restrictive permissions (Unix)."""
    p = path or resolve_tempo_env_path()
    if p is None:
        raise ValueError(
            "No profile selected for Tempo config. Use --profile / BDS_AGENT_PROFILE or run signup.",
        )
    p.parent.mkdir(parents=True, exist_ok=True)
    key = private_key.strip()
    if not key.startswith("0x"):
        key = "0x" + key
    lines = [f"TEMPO_PRIVATE_KEY={key}"]
    if rpc_url and rpc_url.strip():
        lines.append(f"TEMPO_RPC_URL={rpc_url.strip()}")
    if chain_id and str(chain_id).strip():
        lines.append(f"TEMPO_CHAIN_ID={str(chain_id).strip()}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if os.name != "nt":
        p.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return p


def format_plans_json(data: dict) -> str:
    """Human-readable summary of GET /credits/plans."""
    lines: list[str] = []
    plans = data.get("plans") or []
    if not isinstance(plans, list):
        return json.dumps(data, indent=2)
    lines.append(f"primary_recipient: {bundle_primary_recipient(data)}")
    lines.append(f"primary_chain_id: {bundle_primary_chain_id(data)}")
    lines.append(f"primary_rpc_url: {bundle_primary_rpc_url(data)}")
    eu = data.get("epoch_unit") or {}
    if isinstance(eu, dict):
        lines.append(f"epoch_unit: {eu.get('note', '')}")
    lines.append("")
    for pl in plans:
        if not isinstance(pl, dict):
            continue
        if not pl.get("active", True):
            continue
        pid = pl.get("id", "")
        amt = plan_token_amount(pl)
        cr = pl.get("credits", "")
        lines.append(
            f"  plan {pid}: pay {amt} token → {cr} credits  ({pl.get('label', '')})",
        )
    return "\n".join(lines)
