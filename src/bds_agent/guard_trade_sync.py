"""Record guard fills in trader state + trades log (``bds-agent trade status``)."""

from __future__ import annotations

from typing import Any

from bds_agent.active_markets import WatchedPool
from bds_agent.evm_swap import get_erc20_balance_human, get_token_balances_human
from bds_agent.positions import (
    add_position,
    find_position,
    has_open_pool,
    is_paper_position,
    new_position_record,
    normalize_trader_state,
    remove_position,
)
from bds_agent.trader_state import (
    append_trade,
    calculate_pnl_pct,
    calculate_pnl_usd,
    load_trader_state,
    save_trader_state,
    utc_now_iso,
)

_GUARD_ENTRY_ACTIONS = frozenset(
    {"initial_entry_buy", "reentry_buy_dip", "reentry_buy_breakout"},
)
_GUARD_EXIT_ACTIONS = frozenset({"take_profit_sell", "stop_loss_sell"})


def _wallet_address(private_key: str | None) -> str | None:
    if not private_key or not private_key.strip():
        return None
    from eth_account import Account

    return Account.from_key(private_key.strip()).address


def _refresh_balances(
    state: dict[str, Any],
    *,
    rpc_url: str | None,
    wallet: str | None,
    base_token: str,
    base_decimals: int,
) -> dict[str, Any]:
    if not rpc_url or not wallet:
        return state
    usdc_bal, weth_bal = get_token_balances_human(rpc_url, wallet)
    state["usdc_balance"] = usdc_bal
    state["weth_balance"] = weth_bal
    if base_token.lower() == "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2":
        state["token_balance"] = weth_bal
    else:
        state["token_balance"] = get_erc20_balance_human(
            rpc_url,
            base_token,
            wallet,
            base_decimals,
        )
    return state


def record_guard_fill(
    *,
    profile: str | None,
    pool: WatchedPool,
    size_usd: float,
    dry_run: bool,
    guard_state: dict[str, Any],
    action: str,
    result: dict[str, Any],
    price: float | None,
    rpc_url: str | None = None,
    private_key: str | None = None,
) -> None:
    """
    Mirror a executed guard action into ``<profile>.trader.json`` and trades log.

    No-op when the fill was skipped or the action is not a trade.
    """
    if result.get("skipped"):
        return
    act = str(result.get("action") or action)
    if act in _GUARD_ENTRY_ACTIONS:
        _record_guard_entry(
            profile=profile,
            pool=pool,
            size_usd=size_usd,
            dry_run=dry_run,
            guard_state=guard_state,
            action=act,
            result=result,
            price=price,
            rpc_url=rpc_url,
            private_key=private_key,
        )
    elif act in _GUARD_EXIT_ACTIONS:
        _record_guard_exit(
            profile=profile,
            pool=pool,
            size_usd=size_usd,
            dry_run=dry_run,
            guard_state=guard_state,
            action=act,
            result=result,
            price=price,
            rpc_url=rpc_url,
            private_key=private_key,
        )


def _record_guard_entry(
    *,
    profile: str | None,
    pool: WatchedPool,
    size_usd: float,
    dry_run: bool,
    guard_state: dict[str, Any],
    action: str,
    result: dict[str, Any],
    price: float | None,
    rpc_url: str | None,
    private_key: str | None,
) -> None:
    state = normalize_trader_state(load_trader_state(profile))
    if has_open_pool(state, pool.address):
        return
    fill_px = float(result.get("price_usd") or price or 0)
    if action in ("reentry_buy_dip", "reentry_buy_breakout"):
        entry_px = fill_px or float(guard_state.get("reference_entry_usd") or 0)
    else:
        entry_px = float(
            guard_state.get("reference_entry_usd") or fill_px or 0,
        )
    if entry_px <= 0:
        return
    spent = float(result.get("size_usd") or size_usd)
    tx = str(result.get("tx_hash") or ("dry-run" if dry_run else ""))
    ts = utc_now_iso()
    wallet = _wallet_address(private_key)
    token_bal = 0.0
    if rpc_url and wallet and not dry_run:
        token_bal = get_erc20_balance_human(
            rpc_url,
            pool.base_token,
            wallet,
            pool.base_decimals,
        )
    pos = new_position_record(
        pool,
        price=entry_px,
        epoch_i=0,
        size_usd=spent,
        entry_tx=tx or "guard-entry",
        token_balance=token_bal,
        dry_run=bool(dry_run or result.get("dry_run")),
        timestamp=ts,
    )
    state = add_position(state, pos)
    state = _refresh_balances(
        state,
        rpc_url=rpc_url,
        wallet=wallet,
        base_token=pool.base_token,
        base_decimals=pool.base_decimals,
    )
    save_trader_state(state, profile)
    append_trade(
        {
            "type": "ENTRY",
            "direction": "LONG",
            "source": "guard",
            "action": action,
            "price": entry_px,
            "size_usd": spent,
            "pool": pool.address,
            "label": pool.label,
            "tx": tx,
            "dry_run": bool(dry_run or result.get("dry_run")),
            "timestamp": ts,
        },
        profile,
    )


def _record_guard_exit(
    *,
    profile: str | None,
    pool: WatchedPool,
    size_usd: float,
    dry_run: bool,
    guard_state: dict[str, Any],
    action: str,
    result: dict[str, Any],
    price: float | None,
    rpc_url: str | None,
    private_key: str | None,
) -> None:
    state = normalize_trader_state(load_trader_state(profile))
    pos = find_position(state, pool.address)
    entry_px = float(
        (pos or {}).get("entry_price")
        or guard_state.get("reference_entry_usd")
        or 0,
    )
    exit_px = float(price or guard_state.get("last_exit_usd") or 0)
    if entry_px <= 0 or exit_px <= 0:
        return
    trade_size = float((pos or {}).get("size_usd") or size_usd)
    pnl_pct = calculate_pnl_pct(entry_px, exit_px)
    pnl_usd = calculate_pnl_usd(trade_size, pnl_pct)
    tx = str(result.get("tx_hash") or ("dry-run" if dry_run else ""))
    ts = utc_now_iso()
    wallet = _wallet_address(private_key)
    append_trade(
        {
            "type": "EXIT",
            "reason": action,
            "source": "guard",
            "entry_price": entry_px,
            "exit_price": exit_px,
            "pnl_usd": pnl_usd,
            "pnl_pct": pnl_pct,
            "pool": pool.address,
            "label": pool.label,
            "size_usd": trade_size,
            "tx": tx,
            "dry_run": bool(dry_run or result.get("dry_run")),
            "timestamp": ts,
        },
        profile,
    )
    if pos is not None:
        if dry_run and not is_paper_position(pos):
            return
        state = remove_position(state, pool.address)
        state = _refresh_balances(
            state,
            rpc_url=rpc_url,
            wallet=wallet,
            base_token=pool.base_token,
            base_decimals=pool.base_decimals,
        )
        save_trader_state(state, profile)
