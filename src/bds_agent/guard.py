"""Threshold Guard — poll BDS USD Price Feed and execute bracket trades on Uniswap V3."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from web3 import Web3

from bds_agent.active_markets import WatchedPool, fetch_watched_pool
from bds_agent.catalog import DEFAULT_MARKET
from bds_agent.credentials import resolve_profile_name
from bds_agent.evm_swap import get_erc20_balance_human, swap_token_to_usdc, swap_usdc_to_token
from bds_agent.guard_state import load_guard_state, save_guard_state
from bds_agent.prices_cmd import _resolve_api_key, _resolve_base_url
from bds_agent.profile_env import env_or_profile
from bds_agent.trade_config import resolve_trade_wallet
from bds_agent.usd_prices import (
    base_snapshot_project_id,
    fetch_last_finalized_epoch,
    fetch_token_usd_in_pool,
)

Position = Literal["token", "reserve"]


@dataclass
class GuardConfig:
    threshold_high: float
    threshold_low: float
    pool: str | None = None
    base_token: str | None = None
    poll_seconds: float = 15.0
    size_usd: float = 25.0
    slippage: float = 0.005
    dry_run: bool = False
    profile: str | None = None
    max_ticks: int = 0
    bds_namespace: str | None = None
    verbose: bool = False
    enter: bool = False
    enter_min_base: float = 1e-6
    reentry_on_breakout: bool = False


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _bds_namespace(cfg: GuardConfig) -> str:
    if cfg.bds_namespace and str(cfg.bds_namespace).strip():
        return str(cfg.bds_namespace).strip()
    return env_or_profile("BDS_MARKET_NAME") or DEFAULT_MARKET


def resolve_guard_pool_address(cfg: GuardConfig, state: dict[str, Any]) -> str:
    """Pool address from ``--pool`` or persisted ``.guard.json``."""
    if cfg.pool and str(cfg.pool).strip():
        return Web3.to_checksum_address(str(cfg.pool).strip())
    saved = state.get("pool_address")
    if isinstance(saved, str) and saved.strip().startswith("0x"):
        return Web3.to_checksum_address(saved.strip())
    raise RuntimeError(
        "Missing pool: pass --pool <0x…> (USDC-quoted Uniswap V3 pool). "
        "After the first successful run, --pool can be omitted if saved in .guard.json.",
    )


def resolve_guard_base_token(cfg: GuardConfig, pool: WatchedPool) -> str:
    """Base (non-USDC) token for ``GET /mpp/token/price/{token}/{pool}``."""
    if cfg.base_token and str(cfg.base_token).strip():
        tok = Web3.to_checksum_address(str(cfg.base_token).strip())
        if tok.lower() != pool.base_token.lower():
            raise RuntimeError(
                f"--token {tok} does not match pool base token {pool.base_token} "
                f"for {pool.label} ({pool.address})",
            )
        return tok
    return pool.base_token


def _resolve_watched_pool(cfg: GuardConfig, state: dict[str, Any]) -> WatchedPool:
    pool_addr = resolve_guard_pool_address(cfg, state)
    api_key = _resolve_api_key(cfg.profile)
    base_url = _resolve_base_url(cfg.profile)
    try:
        wp = fetch_watched_pool(base_url, api_key, pool_addr)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to resolve pool {pool_addr} from BDS ({base_url}): {exc}",
        ) from exc
    if wp is not None:
        return wp
    raise RuntimeError(
        f"Pool {pool_addr} not found or not USDC-quoted. "
        "Use a USDC-quoted pool with BDS metadata (e.g. USDC/WETH on mainnet)."
    )


def _bds_price_context(
    cfg: GuardConfig,
    pool: WatchedPool,
    *,
    base_token: str,
) -> tuple[float | None, int | None, str]:
    """
    USD spot from BDS at the snapshotter's latest epoch (not RPC chain head).

    Returns (price, epoch_id, base_snapshot_project_id).
    """
    api_key = _resolve_api_key(cfg.profile)
    base_url = _resolve_base_url(cfg.profile)
    namespace = _bds_namespace(cfg)
    project_id = base_snapshot_project_id(pool.address, namespace)
    epoch = fetch_last_finalized_epoch(base_url, api_key, project_id)
    price = fetch_token_usd_in_pool(
        base_url,
        api_key,
        base_token,
        pool.address,
        None,
    )
    return price, epoch, project_id


def _sync_guard_config_state(
    state: dict[str, Any],
    *,
    pool: WatchedPool,
    base_token: str,
    cfg: GuardConfig,
    project_id: str,
) -> None:
    state["pool_address"] = pool.address
    state["pool_label"] = pool.label
    state["base_token"] = base_token
    state["threshold_high"] = cfg.threshold_high
    state["threshold_low"] = cfg.threshold_low
    state["bds_project"] = project_id


def validate_threshold_brackets(threshold_high: float, threshold_low: float) -> None:
    if threshold_high <= threshold_low:
        raise RuntimeError(
            f"--threshold-high ({threshold_high}) must be greater than "
            f"--threshold-low ({threshold_low}). "
            "Example WETH: --threshold-high 2012 --threshold-low 2007.",
        )


def evaluate_threshold_cross(
    *,
    price: float,
    prev_price: float | None,
    position: Position,
    threshold_high: float,
    threshold_low: float,
    reentry_on_breakout: bool = False,
) -> str | None:
    """
    Return action on **band cross** only (not while dwelling inside a band).

    Requires ``prev_price`` from the prior poll so we do not re-fire every tick.

    - **token:** cross up through high → take-profit; cross down through low → stop-loss
    - **reserve:** cross down through low → dip re-entry (default)
    - **reserve:** cross up through high → breakout re-entry (only if ``reentry_on_breakout``)
    """
    if prev_price is None:
        return None

    if position == "token":
        if prev_price < threshold_high <= price:
            return "take_profit_sell"
        if prev_price > threshold_low >= price:
            return "stop_loss_sell"
        return None
    if prev_price > threshold_low >= price:
        return "reentry_buy_dip"
    if reentry_on_breakout and prev_price < threshold_high <= price:
        return "reentry_buy_breakout"
    return None


def _execute_action(
    cfg: GuardConfig,
    pool: WatchedPool,
    action: str,
    price: float,
    *,
    rpc_url: str,
    private_key: str,
) -> dict[str, Any]:
    if cfg.dry_run:
        return {"dry_run": True, "action": action, "price_usd": price}
    if action in ("take_profit_sell", "stop_loss_sell"):
        from eth_account import Account

        owner = Account.from_key(private_key.strip()).address
        balance = get_erc20_balance_human(
            rpc_url,
            pool.base_token,
            owner,
            pool.base_decimals,
        )
        if balance <= 0:
            raise RuntimeError("No base token balance to sell")
        tx = swap_token_to_usdc(
            rpc_url,
            private_key,
            pool,
            balance,
            slippage=cfg.slippage,
            token_price_usd=price,
        )
        return {"action": action, "tx_hash": tx, "new_position": "reserve"}
    if action in ("reentry_buy_dip", "reentry_buy_breakout"):
        tx = swap_usdc_to_token(
            rpc_url,
            private_key,
            pool,
            size_usd=cfg.size_usd,
            slippage=cfg.slippage,
            token_price_usd=price,
        )
        return {"action": action, "tx_hash": tx, "new_position": "token"}
    raise RuntimeError(f"Unknown action: {action}")


def should_initial_entry(cfg: GuardConfig, base_balance_human: float) -> bool:
    """True when ``--enter`` should swap USDC → base before bracket monitoring."""
    if not cfg.enter:
        return False
    return base_balance_human <= cfg.enter_min_base


def execute_initial_entry(
    cfg: GuardConfig,
    pool: WatchedPool,
    *,
    price: float,
    base_balance_human: float,
    rpc_url: str,
    private_key: str,
) -> dict[str, Any]:
    """Buy base token with USDC (enter the pool) using ``cfg.size_usd``."""
    if not should_initial_entry(cfg, base_balance_human):
        return {
            "skipped": True,
            "reason": f"already hold {base_balance_human:g} base (min skip {cfg.enter_min_base:g})",
        }
    if cfg.dry_run:
        return {
            "dry_run": True,
            "action": "initial_entry_buy",
            "size_usd": cfg.size_usd,
            "price_usd": price,
            "new_position": "token",
        }
    tx = swap_usdc_to_token(
        rpc_url,
        private_key,
        pool,
        size_usd=cfg.size_usd,
        slippage=cfg.slippage,
        token_price_usd=price,
    )
    return {
        "action": "initial_entry_buy",
        "tx_hash": tx,
        "size_usd": cfg.size_usd,
        "price_usd": price,
        "new_position": "token",
    }


def run_initial_entry_if_needed(
    cfg: GuardConfig,
    pool: WatchedPool,
    *,
    position: Position,
    price: float | None,
    rpc_url: str,
    private_key: str,
) -> tuple[Position, dict[str, Any] | None]:
    """
    On ``--enter``, swap USDC → base when wallet has negligible base balance.

    Returns updated position (``token`` after a buy) and optional result dict.
    """
    from eth_account import Account

    if not cfg.enter:
        return position, None
    if price is None or price <= 0:
        raise RuntimeError(
            "--enter requires a BDS USD price for sizing the USDC → base swap; "
            "price unavailable on startup",
        )
    owner = Account.from_key(private_key.strip()).address
    base_bal = get_erc20_balance_human(
        rpc_url,
        pool.base_token,
        owner,
        pool.base_decimals,
    )
    if not should_initial_entry(cfg, base_bal):
        return position, {
            "skipped": True,
            "reason": f"already hold {base_bal:g} base",
            "base_balance": base_bal,
        }
    result = execute_initial_entry(
        cfg,
        pool,
        price=price,
        base_balance_human=base_bal,
        rpc_url=rpc_url,
        private_key=private_key,
    )
    new_pos = result.get("new_position", "token")
    if new_pos in ("token", "reserve"):
        position = new_pos
    return position, result


def run_guard_sync(cfg: GuardConfig) -> None:
    validate_threshold_brackets(cfg.threshold_high, cfg.threshold_low)
    state = load_guard_state(cfg.profile)
    pool = _resolve_watched_pool(cfg, state)
    base_token = resolve_guard_base_token(cfg, pool)
    private_key, rpc_url, _chain_id = resolve_trade_wallet()
    position: Position = state.get("position") if state.get("position") in ("token", "reserve") else "token"
    namespace = _bds_namespace(cfg)
    project_id = base_snapshot_project_id(pool.address, namespace)
    _sync_guard_config_state(
        state,
        pool=pool,
        base_token=base_token,
        cfg=cfg,
        project_id=project_id,
    )
    save_guard_state(state, cfg.profile)

    pool_from_state = not (cfg.pool and str(cfg.pool).strip())
    print(
        f"guard pool={pool.label} pool_addr={pool.address} "
        f"base_token={base_token} position={position} "
        f"high={cfg.threshold_high} low={cfg.threshold_low} "
        f"poll={cfg.poll_seconds}s dry_run={cfg.dry_run} "
        f"enter={cfg.enter} size_usd={cfg.size_usd} "
        f"bds_project={project_id}"
        + (" pool_source=state" if pool_from_state else ""),
        flush=True,
    )

    startup_price, startup_epoch, _ = _bds_price_context(cfg, pool, base_token=base_token)
    if cfg.enter:
        position, entry_result = run_initial_entry_if_needed(
            cfg,
            pool,
            position=position,
            price=startup_price,
            rpc_url=rpc_url,
            private_key=private_key,
        )
        state["position"] = position
        state["last_action"] = entry_result
        state["last_price_usd"] = startup_price
        state["last_epoch"] = startup_epoch
        state["updated_at"] = utc_now_iso()
        save_guard_state(state, cfg.profile)
        print(f"[guard] enter {entry_result}", flush=True)

    ticks = 0
    while True:
        ticks += 1
        price, epoch, _ = _bds_price_context(cfg, pool, base_token=base_token)
        pool_tag = pool.address if cfg.verbose else f"{pool.label} {pool.address}"
        if price is None:
            epoch_s = str(epoch) if epoch is not None else "unknown"
            print(
                f"[guard] tick={ticks} pool={pool_tag} base_token={base_token} "
                f"price=unavailable "
                f"(no USD at BDS last-finalized epoch {epoch_s}; "
                f"snapshotter may still be processing)",
                flush=True,
            )
        else:
            epoch_s = str(epoch) if epoch is not None else "latest-submitted"
            raw_prev = state.get("last_price_usd")
            prev_price = float(raw_prev) if isinstance(raw_prev, (int, float)) else None
            action = evaluate_threshold_cross(
                price=price,
                prev_price=prev_price,
                position=position,
                threshold_high=cfg.threshold_high,
                threshold_low=cfg.threshold_low,
                reentry_on_breakout=cfg.reentry_on_breakout,
            )
            print(
                f"[guard] tick={ticks} pool={pool_tag} base_token={base_token} "
                f"bds_epoch={epoch_s} price=${price:.8g} "
                f"position={position} action={action or 'hold'}",
                flush=True,
            )
            if action:
                print(
                    f"[guard] executing {action} (on-chain; may take 1–5 min: "
                    f"pending mempool, approve, swap, confirmation)...",
                    flush=True,
                )
                try:
                    result = _execute_action(
                        cfg,
                        pool,
                        action,
                        price,
                        rpc_url=rpc_url,
                        private_key=private_key,
                    )
                except Exception as exc:
                    print(f"[guard] execute failed: {exc}", flush=True)
                    raise
                position = result.get("new_position", position)
                state["position"] = position
                state["last_action"] = result
                print(f"[guard] executed {result}", flush=True)
            state["last_price_usd"] = price
            state["last_epoch"] = epoch
            state["bds_project"] = project_id
            state["updated_at"] = utc_now_iso()
            save_guard_state(state, cfg.profile)

        if cfg.max_ticks and ticks >= cfg.max_ticks:
            break
        time.sleep(cfg.poll_seconds)


def show_guard_status(profile: str | None = None) -> None:
    prof = profile or resolve_profile_name() or "(none)"
    state = load_guard_state(profile)
    print(f"profile {prof}")
    for key in (
        "pool_address",
        "pool_label",
        "base_token",
        "threshold_high",
        "threshold_low",
        "position",
        "last_price_usd",
        "last_epoch",
        "bds_project",
        "last_action",
        "updated_at",
    ):
        print(f"  {key}: {state.get(key)}")
    if not state.get("pool_address"):
        print(
            "  hint: run guard once with --pool <0x…> and --token <base> (optional) "
            "to pin the watched pool",
        )
