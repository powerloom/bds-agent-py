"""Per-profile trading wallet (`.trade.env`) — separate from billing `.evm.env`."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from bds_agent.credentials import resolve_trade_env_path

# Env keys merged from profiles/<name>.trade.env (do not reuse billing EVM_* keys).
TRADE_PRIVATE_KEY_ENV = "TRADE_EVM_PRIVATE_KEY"
TRADE_RPC_URL_ENV = "TRADE_EVM_RPC_URL"
TRADE_CHAIN_ID_ENV = "TRADE_EVM_CHAIN_ID"


def _merge_env_file(path: Path) -> None:
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


def load_trade_env_file() -> None:
    """Merge `profiles/<name>.trade.env` into os.environ (does not override existing)."""
    path = resolve_trade_env_path()
    if path is not None:
        _merge_env_file(path)


def write_trade_env_file(
    private_key: str,
    *,
    rpc_url: str | None = None,
    chain_id: str | None = None,
    path: Path | None = None,
) -> Path:
    p = path or resolve_trade_env_path()
    if p is None:
        raise ValueError(
            "No profile selected for trade wallet. Set BDS_AGENT_PROFILE, or run: bds-agent trade setup-evm",
        )
    p.parent.mkdir(parents=True, exist_ok=True)
    key = private_key.strip()
    if not key.startswith("0x"):
        key = "0x" + key
    lines = [f"{TRADE_PRIVATE_KEY_ENV}={key}"]
    if rpc_url and rpc_url.strip():
        lines.append(f"{TRADE_RPC_URL_ENV}={rpc_url.strip()}")
    if chain_id and str(chain_id).strip():
        lines.append(f"{TRADE_CHAIN_ID_ENV}={str(chain_id).strip()}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if os.name != "nt":
        p.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return p


def resolve_trade_rpc(*, required: bool = True) -> str:
    """RPC URL from `.trade.env` (no private key)."""
    load_trade_env_file()
    rpc = (os.environ.get(TRADE_RPC_URL_ENV) or "").strip()
    if not rpc and required:
        raise RuntimeError(
            f"{TRADE_RPC_URL_ENV} not set. Run: bds-agent trade setup-evm "
            "(RPC only is enough for guard --dry-run price checks)",
        )
    return rpc


def resolve_trade_chain_id() -> int:
    load_trade_env_file()
    chain_raw = (os.environ.get(TRADE_CHAIN_ID_ENV) or "1").strip()
    try:
        return int(chain_raw)
    except ValueError as e:
        raise RuntimeError(f"Invalid {TRADE_CHAIN_ID_ENV}: {chain_raw!r}") from e


def resolve_trade_wallet() -> tuple[str, str, int]:
    """
    Load trading key/RPC from `.trade.env` only (never billing `.evm.env`).

    Returns (private_key, rpc_url, chain_id).
    """
    load_trade_env_file()
    pk = (os.environ.get(TRADE_PRIVATE_KEY_ENV) or "").strip()
    if not pk or pk == "0x":
        raise RuntimeError(
            f"{TRADE_PRIVATE_KEY_ENV} not set. Run: bds-agent trade setup-evm",
        )
    if not pk.startswith("0x"):
        pk = "0x" + pk
    rpc = resolve_trade_rpc(required=True)
    chain_id = resolve_trade_chain_id()
    return pk, rpc, chain_id
