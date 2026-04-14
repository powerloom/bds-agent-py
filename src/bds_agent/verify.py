"""
On-chain verification: compare stream ``verification.cid`` to ProtocolState ``maxSnapshotsCid``.

The view call is ``ProtocolState.maxSnapshotsCid(dataMarket, projectId, epochId)``, which forwards
to ``dataMarket.maxSnapshotsCid(projectId, epochId)`` (see ProtocolState.sol). The JSON-RPC
``eth_call`` uses ``to = protocolState``; the **DataMarket** contract address is the first encoded
argument. Both addresses must be correct: wrong ProtocolState or wrong DataMarket pair yields a
wrong or empty CID.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx
from eth_abi import decode, encode
from eth_utils import keccak, to_checksum_address

from bds_agent.config import AgentConfig
from bds_agent.profile_env import env_or_profile

_MAX_SNAPSHOTS_CID_SELECTOR = keccak(text="maxSnapshotsCid(address,string,uint256)")[:4]


class VerifyError(Exception):
    """JSON-RPC failure, bad response, or decoding error."""


@dataclass(frozen=True)
class VerificationPayload:
    cid: str
    epoch_id: int
    project_id: str
    protocol_state: str
    data_market: str


@dataclass(frozen=True)
class VerifyResult:
    match: bool
    stream_cid: str
    on_chain_cid: str
    status: int


def parse_verification(data: dict) -> VerificationPayload | None:
    """Extract ``verification`` from an SSE chunk payload (or equivalent)."""
    v = data.get("verification")
    if not isinstance(v, dict):
        return None
    try:
        cid = v.get("cid")
        epoch_id = v.get("epochId")
        project_id = v.get("projectId")
        ps = v.get("protocolState")
        dm = v.get("dataMarket")
        if not isinstance(cid, str) or not isinstance(project_id, str):
            return None
        if not isinstance(ps, str) or not isinstance(dm, str):
            return None
        if epoch_id is None:
            return None
        ei = int(epoch_id)
        return VerificationPayload(
            cid=cid,
            epoch_id=ei,
            project_id=project_id,
            protocol_state=ps,
            data_market=dm,
        )
    except (TypeError, ValueError):
        return None


def _encode_max_snapshots_cid_call(
    data_market: str,
    project_id: str,
    epoch_id: int,
) -> bytes:
    return _MAX_SNAPSHOTS_CID_SELECTOR + encode(
        ["address", "string", "uint256"],
        [
            to_checksum_address(data_market),
            project_id,
            epoch_id,
        ],
    )


def _decode_max_snapshots_cid_return(result_hex: str) -> tuple[str, int]:
    h = (result_hex or "").strip()
    if not h or h == "0x":
        return "", 0
    if h.startswith("0x"):
        h = h[2:]
    raw = bytes.fromhex(h)
    cid, status_u8 = decode(["string", "uint8"], raw)
    return cid, int(status_u8)


def resolve_verify_rpc_url(cfg: AgentConfig) -> str | None:
    """Precedence: ``agent.yaml`` ``verify_rpc_url`` → ``POWERLOOM_RPC_URL`` env/profile."""
    if cfg.verify_rpc_url and str(cfg.verify_rpc_url).strip():
        return str(cfg.verify_rpc_url).strip()
    env = os.environ.get("POWERLOOM_RPC_URL", "").strip()
    if env:
        return env
    v = env_or_profile("POWERLOOM_RPC_URL")
    return v if v else None


def resolve_verify_protocol_state(cfg: AgentConfig, payload: VerificationPayload) -> str | None:
    """Precedence: ``agent.yaml`` ``verify_protocol_state`` → ``POWERLOOM_PROTOCOL_STATE`` env/profile → payload."""
    if cfg.verify_protocol_state and str(cfg.verify_protocol_state).strip():
        return str(cfg.verify_protocol_state).strip()
    env = os.environ.get("POWERLOOM_PROTOCOL_STATE", "").strip()
    if env:
        return env
    v = env_or_profile("POWERLOOM_PROTOCOL_STATE")
    if v:
        return v
    ps = (payload.protocol_state or "").strip()
    return ps if ps else None


def resolve_verify_data_market(cfg: AgentConfig, payload: VerificationPayload) -> str | None:
    """Precedence: ``agent.yaml`` ``verify_data_market`` → ``POWERLOOM_DATA_MARKET`` env/profile → payload."""
    if cfg.verify_data_market and str(cfg.verify_data_market).strip():
        return str(cfg.verify_data_market).strip()
    env = os.environ.get("POWERLOOM_DATA_MARKET", "").strip()
    if env:
        return env
    v = env_or_profile("POWERLOOM_DATA_MARKET")
    if v:
        return v
    dm = (payload.data_market or "").strip()
    return dm if dm else None


async def verify_cid(
    payload: VerificationPayload,
    *,
    rpc_url: str,
    protocol_state: str,
    data_market: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> VerifyResult:
    """
    ``eth_call`` to **ProtocolState** with ``maxSnapshotsCid(dataMarket, projectId, epochId)``.
    ``data_market`` is the Powerloom DataMarket contract (first ABI argument); ``protocol_state`` is
    the ``to`` address. Compare returned CID to ``payload.cid``.
    """
    dm = (data_market or payload.data_market).strip()
    ps = protocol_state.strip()
    if not ps:
        raise VerifyError("protocol state address is empty")
    if not dm:
        raise VerifyError("data market address is empty")
    calldata = _encode_max_snapshots_cid_call(
        dm,
        payload.project_id,
        payload.epoch_id,
    )
    to_addr = to_checksum_address(ps)
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": to_addr, "data": "0x" + calldata.hex()}, "latest"],
    }

    own_client = client is None
    c = client or httpx.AsyncClient(timeout=60.0)
    try:
        resp = await c.post(rpc_url, json=req)
        resp.raise_for_status()
        body = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        raise VerifyError(f"RPC request failed: {e}") from e
    finally:
        if own_client:
            await c.aclose()

    if not isinstance(body, dict):
        raise VerifyError("RPC response is not an object")
    err = body.get("error")
    if err is not None:
        raise VerifyError(f"RPC error: {err!r}")
    result_hex = body.get("result")
    if not isinstance(result_hex, str):
        raise VerifyError("RPC result missing or not a hex string")

    on_chain_cid, status = _decode_max_snapshots_cid_return(result_hex)
    stream_cid = payload.cid.strip()
    match = on_chain_cid == stream_cid
    return VerifyResult(
        match=match,
        stream_cid=stream_cid,
        on_chain_cid=on_chain_cid,
        status=status,
    )
