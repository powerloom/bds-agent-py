"""Per-profile Ethereum key and RPC for pay-to-signup and on-chain credit purchase (Tempo top-up uses `.tempo.env` instead)."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from bds_agent.credentials import resolve_evm_env_path
from bds_agent.paths import config_dir


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


def load_evm_env_file() -> None:
    """Merge `profiles/<name>.evm.env` (and legacy `~/.config/bds-agent/evm.env`) into os.environ."""
    path = resolve_evm_env_path()
    if path is not None:
        _merge_env_file(path)
    legacy = config_dir() / "evm.env"
    if legacy.is_file():
        _merge_env_file(legacy)


def write_evm_env_file(
    private_key: str,
    *,
    rpc_url: str | None = None,
    chain_id: str | None = None,
    path: Path | None = None,
) -> Path:
    p = path or resolve_evm_env_path()
    if p is None:
        raise ValueError(
            "No profile selected for EVM config. Set BDS_AGENT_PROFILE, or run: bds-agent credits setup-evm",
        )
    p.parent.mkdir(parents=True, exist_ok=True)
    key = private_key.strip()
    if not key.startswith("0x"):
        key = "0x" + key
    lines = [f"EVM_PRIVATE_KEY={key}"]
    if rpc_url and rpc_url.strip():
        lines.append(f"EVM_RPC_URL={rpc_url.strip()}")
    if chain_id and str(chain_id).strip():
        lines.append(f"EVM_CHAIN_ID={str(chain_id).strip()}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if os.name != "nt":
        p.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return p
