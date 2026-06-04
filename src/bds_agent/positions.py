"""Multi-pool trader: concurrent LONG positions (one per pool)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bds_agent.active_markets import WatchedPool
from bds_agent.trader_state import (
    default_trader_state,
    is_reentry_blocked,
    utc_now_iso,
)

_LEGACY_POSITION_KEYS = (
    "position",
    "entry_price",
    "entry_epoch",
    "entry_timestamp",
    "entry_tx",
    "size_usd",
    "peak_price",
    "entry_pool",
    "entry_label",
    "entry_token",
    "entry_token0",
    "entry_token1",
    "entry_base_idx",
    "entry_fee",
    "entry_base_decimals",
    "token_balance",
    "dry_run_position",
)


def _pool_key(pool: str) -> str:
    return pool.strip().lower()


def open_positions(state: dict[str, Any]) -> list[dict[str, Any]]:
    raw = state.get("positions")
    if not isinstance(raw, list):
        return []
    return [p for p in raw if isinstance(p, dict) and p.get("entry_pool")]


def position_count(state: dict[str, Any]) -> int:
    return len(open_positions(state))


def open_pool_keys(state: dict[str, Any]) -> set[str]:
    return {_pool_key(str(p["entry_pool"])) for p in open_positions(state)}


def has_open_pool(state: dict[str, Any], pool: str) -> bool:
    return _pool_key(pool) in open_pool_keys(state)


def find_position(state: dict[str, Any], pool: str) -> dict[str, Any] | None:
    key = _pool_key(pool)
    for pos in open_positions(state):
        if _pool_key(str(pos.get("entry_pool") or "")) == key:
            return pos
    return None


def _legacy_position_from_state(state: dict[str, Any]) -> dict[str, Any]:
    from bds_agent.evm_swap import USDC, USDC_WETH_POOL_005

    entry_pool = state.get("entry_pool") or USDC_WETH_POOL_005
    return {
        "entry_pool": entry_pool,
        "entry_label": state.get("entry_label") or "USDC/WETH",
        "entry_token": state.get("entry_token") or "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "entry_token0": state.get("entry_token0") or USDC,
        "entry_token1": state.get("entry_token1") or "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "entry_base_idx": state.get("entry_base_idx") if state.get("entry_base_idx") is not None else 1,
        "entry_fee": state.get("entry_fee") or 500,
        "entry_base_decimals": state.get("entry_base_decimals") or 18,
        "entry_price": state.get("entry_price"),
        "peak_price": state.get("peak_price"),
        "entry_epoch": state.get("entry_epoch"),
        "entry_timestamp": state.get("entry_timestamp"),
        "entry_tx": state.get("entry_tx"),
        "size_usd": state.get("size_usd"),
        "token_balance": state.get("token_balance") or state.get("weth_balance") or 0.0,
        "dry_run": bool(state.get("dry_run_position") or state.get("entry_tx") == "dry-run"),
    }


def sync_legacy_top_level(state: dict[str, Any]) -> dict[str, Any]:
    """Mirror first open position into legacy single-position fields for older callers."""
    positions = open_positions(state)
    base = default_trader_state()
    if len(positions) == 1:
        pos = positions[0]
        state["position"] = "LONG"
        state["entry_price"] = pos.get("entry_price")
        state["peak_price"] = pos.get("peak_price")
        state["entry_epoch"] = pos.get("entry_epoch")
        state["entry_timestamp"] = pos.get("entry_timestamp")
        state["entry_tx"] = pos.get("entry_tx")
        state["size_usd"] = pos.get("size_usd")
        state["entry_pool"] = pos.get("entry_pool")
        state["entry_label"] = pos.get("entry_label")
        state["entry_token"] = pos.get("entry_token")
        state["entry_token0"] = pos.get("entry_token0")
        state["entry_token1"] = pos.get("entry_token1")
        state["entry_base_idx"] = pos.get("entry_base_idx")
        state["entry_fee"] = pos.get("entry_fee")
        state["entry_base_decimals"] = pos.get("entry_base_decimals")
        state["token_balance"] = pos.get("token_balance")
        state["dry_run_position"] = bool(pos.get("dry_run"))
        if pos.get("entry_token", "").lower() == "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2":
            state["weth_balance"] = pos.get("token_balance")
    elif len(positions) == 0:
        for key in _LEGACY_POSITION_KEYS:
            state[key] = base.get(key)
    else:
        state["position"] = "LONG"
        state["entry_pool"] = None
        state["entry_label"] = f"{len(positions)} open"
        state["dry_run_position"] = any(p.get("dry_run") for p in positions)
    return state


def normalize_trader_state(state: dict[str, Any]) -> dict[str, Any]:
    positions_raw = state.get("positions")
    positions: list[dict[str, Any]]
    if isinstance(positions_raw, list):
        positions = [p for p in positions_raw if isinstance(p, dict) and p.get("entry_pool")]
    else:
        positions = []
    if not positions and state.get("position") == "LONG":
        positions = [_legacy_position_from_state(state)]
    state["positions"] = positions
    if not isinstance(state.get("pool_reentry_blocked"), dict):
        state["pool_reentry_blocked"] = {}
    return sync_legacy_top_level(state)


def is_paper_position(pos: dict[str, Any]) -> bool:
    return bool(pos.get("dry_run") or pos.get("entry_tx") == "dry-run")


def position_sell_tokens(
    pos: dict[str, Any] | None,
    wallet_balance: float,
    *,
    fallback_size_usd: float = 0.0,
    fallback_price_usd: float = 0.0,
) -> float:
    """Human base amount to sell — position record capped by wallet (not full wallet)."""
    if wallet_balance <= 0:
        return 0.0
    if pos is not None:
        recorded = float(pos.get("token_balance") or 0.0)
        if recorded > 0:
            return min(recorded, wallet_balance)
    if fallback_size_usd > 0 and fallback_price_usd > 0:
        est = fallback_size_usd / fallback_price_usd
        return min(wallet_balance, est)
    return wallet_balance


def is_dry_run_open(state: dict[str, Any]) -> bool:
    return any(is_paper_position(p) for p in open_positions(state))


def strip_dry_run_positions(state: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Remove paper positions only; keep live LONGs. Returns (state, removed_count)."""
    state = normalize_trader_state(state)
    before = open_positions(state)
    removed_pools = [
        _pool_key(str(p.get("entry_pool") or ""))
        for p in before
        if is_paper_position(p)
    ]
    kept = [p for p in before if not is_paper_position(p)]
    removed = len(before) - len(kept)
    state["positions"] = kept
    blocked = state.get("pool_reentry_blocked")
    if isinstance(blocked, dict):
        for pk in removed_pools:
            blocked.pop(pk, None)
    if removed > 0 and not kept:
        state["reentry_blocked_until"] = None
    return sync_legacy_top_level(state), removed


def exit_state_view(pos: dict[str, Any]) -> dict[str, Any]:
    return {
        "position": "LONG",
        "entry_price": pos.get("entry_price"),
        "peak_price": pos.get("peak_price"),
        "entry_timestamp": pos.get("entry_timestamp"),
    }


def pool_from_position(pos: dict[str, Any]) -> WatchedPool | None:
    addr = pos.get("entry_pool")
    if not isinstance(addr, str) or not addr.startswith("0x"):
        return None
    t0 = pos.get("entry_token0")
    t1 = pos.get("entry_token1")
    if not isinstance(t0, str) or not isinstance(t1, str):
        return None
    try:
        base_idx = int(pos.get("entry_base_idx") if pos.get("entry_base_idx") is not None else 1)
        fee = int(pos.get("entry_fee") or 3000)
        base_decimals = int(pos.get("entry_base_decimals") or 18)
    except (TypeError, ValueError):
        return None
    return WatchedPool(
        address=addr,
        token0=t0,
        token1=t1,
        base_idx=base_idx,
        label=str(pos.get("entry_label") or ""),
        fee=fee,
        base_decimals=base_decimals,
    )


def entry_fields_from_pool(pool: WatchedPool) -> dict[str, Any]:
    return {
        "entry_pool": pool.address,
        "entry_label": pool.label,
        "entry_token": pool.base_token,
        "entry_token0": pool.token0,
        "entry_token1": pool.token1,
        "entry_base_idx": pool.base_idx,
        "entry_fee": pool.fee,
        "entry_base_decimals": pool.base_decimals,
    }


def new_position_record(
    pool: WatchedPool,
    *,
    price: float | None,
    epoch_i: int,
    size_usd: float,
    entry_tx: str,
    token_balance: float = 0.0,
    dry_run: bool = False,
    timestamp: str | None = None,
) -> dict[str, Any]:
    ts = timestamp or utc_now_iso()
    return {
        **entry_fields_from_pool(pool),
        "entry_price": price,
        "peak_price": price,
        "entry_epoch": epoch_i,
        "entry_timestamp": ts,
        "entry_tx": entry_tx,
        "size_usd": size_usd,
        "token_balance": token_balance,
        "dry_run": dry_run,
    }


def add_position(state: dict[str, Any], pos: dict[str, Any]) -> dict[str, Any]:
    positions = list(open_positions(state))
    positions.append(pos)
    state["positions"] = positions
    return sync_legacy_top_level(state)


def remove_position(state: dict[str, Any], pool: str) -> dict[str, Any]:
    key = _pool_key(pool)
    state["positions"] = [
        p for p in open_positions(state) if _pool_key(str(p.get("entry_pool") or "")) != key
    ]
    return sync_legacy_top_level(state)


def _parse_until(raw: str) -> datetime | None:
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def is_pool_reentry_blocked(
    state: dict[str, Any],
    pool: str,
    *,
    now: datetime | None = None,
) -> bool:
    blocked = state.get("pool_reentry_blocked")
    if not isinstance(blocked, dict):
        return False
    raw = blocked.get(_pool_key(pool))
    if not raw or not isinstance(raw, str):
        return False
    until = _parse_until(raw)
    if until is None:
        return False
    now_dt = now or datetime.now(UTC)
    return now_dt.astimezone(UTC) < until


def set_pool_reentry_cooldown(
    state: dict[str, Any],
    pool: str,
    cooldown_minutes: float,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    key = _pool_key(pool)
    blocked = state.get("pool_reentry_blocked")
    if not isinstance(blocked, dict):
        blocked = {}
        state["pool_reentry_blocked"] = blocked
    if cooldown_minutes <= 0:
        blocked.pop(key, None)
        return state
    from datetime import timedelta

    now_dt = now or datetime.now(UTC)
    until = now_dt + timedelta(minutes=cooldown_minutes)
    blocked[key] = until.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return state


def can_enter_pool(
    state: dict[str, Any],
    pool: str,
    *,
    max_open_positions: int,
    daily_loss_limit_hit: bool,
    use_global_reentry: bool = False,
) -> tuple[bool, str | None]:
    if has_open_pool(state, pool):
        return False, "already_in_pool"
    if position_count(state) >= max(1, max_open_positions):
        return False, "max_positions"
    if is_pool_reentry_blocked(state, pool):
        return False, "reentry_cooldown"
    if use_global_reentry and is_reentry_blocked(state):
        return False, "reentry_cooldown"
    if daily_loss_limit_hit:
        return False, "daily_loss_limit"
    return True, None


def aggregate_position_label(state: dict[str, Any]) -> str:
    n = position_count(state)
    if n == 0:
        return "FLAT"
    if n == 1:
        return "LONG"
    return f"LONG×{n}"
