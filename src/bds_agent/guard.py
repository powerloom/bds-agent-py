"""Threshold Guard — poll BDS USD Price Feed and execute bracket trades on Uniswap V3."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal

from rich.console import Console
from web3 import Web3

from bds_agent.active_markets import WatchedPool, fetch_watched_pool
from bds_agent.credentials import resolve_profile_name
from bds_agent.evm_swap import get_erc20_balance_human, swap_token_to_usdc, swap_usdc_to_token
from bds_agent.guard_state import load_guard_state, save_guard_state
from bds_agent.prices_cmd import _resolve_api_key, _resolve_base_url
from bds_agent.trade_config import (
    resolve_trade_chain_id,
    resolve_trade_rpc,
    resolve_trade_wallet,
)
from bds_agent.tty_console import TimestampedConsole, format_price_px, make_tty_console
from bds_agent.usd_prices import fetch_token_usd_in_pool

PricingMode = Literal["spot", "explicit"]
DEFAULT_TAKE_PROFIT_PCT = 0.03

Position = Literal["token", "reserve"]


@dataclass
class GuardConfig:
    """Spot mode (default): enter at BDS spot; exit at +take-profit %%; dip-reenter after partial giveback."""

    pool: str | None = None
    base_token: str | None = None
    poll_seconds: float = 15.0
    size_usd: float = 25.0
    slippage: float = 0.005
    dry_run: bool = False
    profile: str | None = None
    max_ticks: int = 0
    verbose: bool = False
    enter: bool | None = None
    enter_min_base: float = 1e-6
    # Explicit USD bands (compose / advanced)
    threshold_high: float | None = None
    threshold_low: float | None = None
    reentry_on_breakout: bool = False
    # Spot mode (% moves from entry / last exit)
    take_profit_pct: float | None = None
    stop_loss_pct: float | None = None
    reentry_retrace_pct: float = 0.5
    # Exit guard after N minutes in USDC waiting for dip re-entry (0 = wait forever).
    reserve_max_minutes: float = 0.0


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


def _parse_iso_utc(raw: str | None) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
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


def sync_reserve_since(state: dict[str, Any], position: Position) -> None:
    """Track when we entered USDC (reserve) for idle timeout."""
    if position == "reserve":
        if not state.get("reserve_since"):
            state["reserve_since"] = utc_now_iso()
    else:
        state.pop("reserve_since", None)


def reserve_idle_seconds(
    state: dict[str, Any],
    *,
    now: datetime | None = None,
) -> float | None:
    if state.get("position") != "reserve":
        return None
    started = _parse_iso_utc(state.get("reserve_since"))
    if started is None:
        return None
    now_dt = now or datetime.now(tz=UTC)
    return max(0.0, (now_dt - started).total_seconds())


def reserve_idle_timed_out(reserve_max_minutes: float, state: dict[str, Any]) -> bool:
    if reserve_max_minutes <= 0:
        return False
    elapsed = reserve_idle_seconds(state)
    if elapsed is None:
        return False
    return elapsed >= reserve_max_minutes * 60.0


def _allow_reserve_enter(
    cfg: GuardConfig,
    state: dict[str, Any],
    position: Position,
    *,
    begin_new_leg: bool,
    pending_initial_entry: bool = False,
) -> bool:
    """USDC (reserve) + ``--enter``: fresh leg or post-``guard reset``, not mid-cycle dip wait."""
    if position != "reserve":
        return False
    if pending_initial_entry:
        return True
    if not cfg.enter:
        return False
    if begin_new_leg:
        return True
    ref = state.get("reference_entry_usd")
    return ref is None or (isinstance(ref, (int, float)) and float(ref) <= 0)


def prepare_guard_run_state(
    state: dict[str, Any],
    cfg: GuardConfig,
) -> tuple[dict[str, Any], bool]:
    """
    Bookkeeping at the start of ``guard run``.

    Returns ``(state, begin_new_leg)``. When the prior run ended with
    ``reserve_idle_timeout`` and this run uses ``--enter``, ``begin_new_leg`` is
    True so a fresh USDC → base entry is allowed (orchestrator re-launch).
    """
    new_leg = False
    if state.get("fresh_leg") and cfg.enter:
        new_leg = True
        state.pop("fresh_leg", None)
        state.pop("reference_entry_usd", None)
        state.pop("last_exit_usd", None)
        state.pop("reserve_since", None)
        state["last_action"] = None
    if state.get("guard_exit_reason") == "reserve_idle_timeout":
        state.pop("guard_exit_reason", None)
        if cfg.enter:
            new_leg = True
            state.pop("reference_entry_usd", None)
            state.pop("last_exit_usd", None)
            state.pop("reserve_since", None)
            state["last_action"] = None
    if state.get("position") == "reserve" and cfg.reserve_max_minutes > 0:
        if reserve_idle_timed_out(cfg.reserve_max_minutes, state):
            state["reserve_since"] = utc_now_iso()
        elif not state.get("reserve_since"):
            sync_reserve_since(state, "reserve")
    return state, new_leg


def _reserve_idle_note(cfg: GuardConfig, state: dict[str, Any]) -> str:
    if cfg.reserve_max_minutes <= 0 or state.get("position") != "reserve":
        return ""
    elapsed = reserve_idle_seconds(state)
    if elapsed is None:
        return ""
    limit_s = cfg.reserve_max_minutes * 60.0
    max(0.0, limit_s - elapsed)
    return f" [dim]reserve_idle={int(elapsed)}s/{int(limit_s)}s[/]"


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


def _resolve_guard_evm(cfg: GuardConfig) -> tuple[str | None, str | None, int]:
    """
    Trading credentials for guard.

    Dry-run: no private key; RPC optional (for on-chain pool enrichment only).
    Live: full ``resolve_trade_wallet()``.
    """
    if cfg.dry_run:
        try:
            rpc = resolve_trade_rpc(required=False)
        except RuntimeError:
            rpc = ""
        rpc = rpc.strip() if rpc else None
        return None, rpc, resolve_trade_chain_id()
    pk, rpc, chain_id = resolve_trade_wallet()
    return pk, rpc, chain_id


def _prepare_guard_pool(
    cfg: GuardConfig,
    state: dict[str, Any],
    *,
    rpc_url: str | None,
) -> tuple[WatchedPool, str]:
    """BDS pool metadata, optional on-chain enrich, then base token for price routes."""
    from bds_agent.evm_swap import enrich_watched_pool_fee

    pool = _resolve_watched_pool(cfg, state)
    if rpc_url:
        pool = enrich_watched_pool_fee(rpc_url, pool)
    base_token = resolve_guard_base_token(cfg, pool)
    return pool, base_token


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


def _fetch_guard_price_usd(
    cfg: GuardConfig,
    pool: WatchedPool,
    *,
    base_token: str,
    out: Console | None = None,
) -> float | None:
    """
    Pool-scoped USD price from BDS (resolver picks latest snapshot server-side).

    No ``last_finalized_epoch`` or snapshot project id — those are resolver internals.
    """
    api_key = _resolve_api_key(cfg.profile)
    base_url = _resolve_base_url(cfg.profile)

    def on_retry(attempt: int, reason: str) -> None:
        if out is not None:
            out.print(
                f"[yellow]PRICE RETRY[/] attempt {attempt} ({reason}) "
                "[dim]— transient BDS/gateway; backing off[/]",
            )

    return fetch_token_usd_in_pool(
        base_url,
        api_key,
        base_token,
        pool.address,
        None,
        on_retry=on_retry if out is not None else None,
    )


def guard_pricing_mode(cfg: GuardConfig) -> PricingMode:
    if cfg.threshold_high is not None and cfg.threshold_low is not None:
        return "explicit"
    return "spot"


def normalize_guard_config(cfg: GuardConfig) -> GuardConfig:
    """Resolve spot vs explicit mode and defaults before run."""
    if (cfg.threshold_high is None) != (cfg.threshold_low is None):
        raise RuntimeError(
            "Pass both --threshold-high and --threshold-low for explicit mode, "
            "or neither for spot mode (--take-profit-pct).",
        )
    mode = guard_pricing_mode(cfg)
    if mode == "explicit":
        validate_threshold_brackets(cfg.threshold_high, cfg.threshold_low)
        enter = cfg.enter if cfg.enter is not None else False
        return replace(cfg, enter=enter, take_profit_pct=None)
    tp = cfg.take_profit_pct if cfg.take_profit_pct is not None else DEFAULT_TAKE_PROFIT_PCT
    if tp <= 0:
        raise RuntimeError("--take-profit-pct must be > 0 (e.g. 0.03 for +3%).")
    if not 0 < cfg.reentry_retrace_pct <= 1:
        raise RuntimeError("--reentry-retrace-pct must be in (0, 1] (default 0.5 = half the gain).")
    if cfg.stop_loss_pct is not None:
        sl = float(cfg.stop_loss_pct)
        if sl <= 0 or sl >= 1:
            raise RuntimeError("--stop-loss-pct must be in (0, 1) (e.g. 0.02 for -2%).")
    if cfg.reserve_max_minutes < 0:
        raise RuntimeError("--reserve-max-minutes must be >= 0 (0 = no idle exit).")
    enter = cfg.enter if cfg.enter is not None else True
    return replace(
        cfg,
        enter=enter,
        take_profit_pct=tp,
        threshold_high=None,
        threshold_low=None,
    )


# Internal reserve high band: blocks breakout re-entry in spot mode (not shown in logs).
_RESERVE_BREAKOUT_BLOCK = 1e6


def format_guard_band_log(
    cfg: GuardConfig,
    state: dict[str, Any],
    *,
    position: Position,
    band_high: float,
    band_low: float,
) -> str:
    if guard_pricing_mode(cfg) == "explicit":
        return (
            f" [dim]low=[/][yellow]${band_low:g}[/]"
            f" [dim]high=[/][green]${band_high:g}[/]"
        )
    if position == "token":
        stop_s = (
            f" [dim]stop=[/][yellow]${band_low:g}[/]"
            if band_low > 0
            else ""
        )
        return f"{stop_s} [dim]tp=[/][green]${band_high:g}[/]"
    exit_raw = state.get("last_exit_usd")
    exit_s = ""
    if exit_raw is not None and float(exit_raw) > 0:
        exit_s = f" [dim]last_exit=[/][bold]{format_price_px(float(exit_raw))}[/]"
    return f"{exit_s} [dim]reentry_below=[/][cyan]${band_low:g}[/]"


def _guard_position_markup(position: Position) -> str:
    if position == "token":
        return "[bold green]token[/]"
    return "[bold cyan]reserve[/]"


def _guard_action_markup(action: str | None) -> str:
    if not action or action == "hold":
        return "[dim]hold[/]"
    if action in ("take_profit_sell", "reentry_buy_dip", "reentry_buy_breakout", "initial_entry_buy"):
        return f"[bold green]{action}[/]"
    if action == "stop_loss_sell":
        return f"[bold red]{action}[/]"
    return f"[bold yellow]{action}[/]"


def _guard_pool_tag(cfg: GuardConfig, pool: WatchedPool) -> str:
    if cfg.verbose:
        return pool.address
    return f"{pool.label} [dim]{pool.address}[/]"


def _print_guard_startup(
    out: Console,
    *,
    cfg: GuardConfig,
    pool: WatchedPool,
    base_token: str,
    position: Position,
    mode: str,
    chain_id: int,
    bands_note: str,
    wallet_line: str,
    pool_from_state: bool,
) -> None:
    enter_s = "[green]on[/]" if cfg.enter else "[dim]off[/]"
    dry_s = "[yellow]dry_run[/]" if cfg.dry_run else "[dim]live[/]"
    out.print(
        f"[bold blue]GUARD[/] [bold]{pool.label}[/] [dim]{pool.address}[/] "
        f"base=[cyan]{base_token}[/] pos={_guard_position_markup(position)} "
        f"mode=[cyan]{mode}[/] poll={cfg.poll_seconds}s {dry_s} enter={enter_s} "
        f"size=${cfg.size_usd:g} fee={pool.fee} chain={chain_id}{bands_note} "
        f"{wallet_line}"
        + (f" tp%={effective_take_profit_pct(cfg):g}"
           f" sl%={cfg.stop_loss_pct!s}"
           f" retrace={cfg.reentry_retrace_pct:g}" if mode == "spot" else "")
        + (
            f" reserve_max={cfg.reserve_max_minutes:g}m"
            if cfg.reserve_max_minutes > 0
            else ""
        )
        + (" [dim]pool_source=state[/]" if pool_from_state else ""),
    )


def _print_guard_tick(
    out: Console,
    *,
    ticks: int,
    pool_tag: str,
    base_token: str,
    price: float | None,
    position: Position,
    band_s: str,
    action: str | None,
    band_err: str | None,
    idle_note: str = "",
) -> None:
    pos_m = _guard_position_markup(position)
    act_m = _guard_action_markup(action)
    err_s = f" [red]({band_err})[/]" if band_err else ""
    if price is None:
        out.print(
            f"[bold blue]GUARD[/] [dim]tick={ticks}[/] {pool_tag} "
            f"base=[dim]{base_token}[/] [yellow]price=unavailable[/] "
            f"pos={pos_m} {act_m}{err_s}{idle_note} "
            "[dim italic](no USD from BDS; snapshotter may still be processing)[/]",
        )
        return
    out.print(
        f"[bold blue]GUARD[/] [dim]tick={ticks}[/] {pool_tag} "
        f"px=[bold]{format_price_px(price)}[/] pos={pos_m}{band_s}{idle_note} "
        f"→ {act_m}{err_s}",
    )


def effective_take_profit_pct(cfg: GuardConfig) -> float:
    if cfg.take_profit_pct is None:
        return DEFAULT_TAKE_PROFIT_PCT
    return float(cfg.take_profit_pct)


def resolve_guard_bands(
    cfg: GuardConfig,
    state: dict[str, Any],
    *,
    position: Position,
) -> tuple[float, float]:
    """
    USD levels for edge-triggered crosses.

    Spot + token: take profit at entry * (1 + take_profit_pct);
    optional stop loss at entry * (1 - stop_loss_pct).
    Spot + reserve: re-enter on cross **down** — after a win, partial giveback
    of the gain; after a stop, a further dip below the exit (cheaper re-entry).
    """
    if guard_pricing_mode(cfg) == "explicit":
        return float(cfg.threshold_high), float(cfg.threshold_low)

    if position == "reserve":
        exit_raw = state.get("last_exit_usd")
        if exit_raw is None or float(exit_raw) <= 0:
            raise RuntimeError(
                "Spot mode in USDC (reserve) needs last_exit_usd from a prior exit, "
                "or run with --enter to open a new leg.",
            )
        exit_price = float(exit_raw)
        retrace = cfg.reentry_retrace_pct
        entry_raw = state.get("reference_entry_usd")
        if entry_raw is not None and float(entry_raw) > 0:
            entry = float(entry_raw)
            margin = exit_price - entry
            if margin > 0:
                reentry = exit_price - retrace * margin
            else:
                reentry = exit_price - retrace * (entry - exit_price)
        elif cfg.stop_loss_pct is not None and float(cfg.stop_loss_pct) > 0:
            sl = float(cfg.stop_loss_pct)
            reentry = exit_price * (1.0 - retrace * sl)
        else:
            reentry = exit_price * (1.0 - retrace * effective_take_profit_pct(cfg))
        return exit_price * _RESERVE_BREAKOUT_BLOCK, reentry

    entry_raw = state.get("reference_entry_usd")
    if entry_raw is None or float(entry_raw) <= 0:
        raise RuntimeError(
            "Spot mode needs a reference entry price. Run with --enter, or set "
            "reference_entry_usd in .guard.json after a buy.",
        )
    entry = float(entry_raw)
    tp = effective_take_profit_pct(cfg)
    high = entry * (1.0 + tp)
    if cfg.stop_loss_pct is not None and cfg.stop_loss_pct > 0:
        low = entry * (1.0 - float(cfg.stop_loss_pct))
    else:
        low = 0.0
    return high, low


def _after_guard_fill(
    *,
    cfg: GuardConfig,
    pool: WatchedPool,
    state: dict[str, Any],
    action: str,
    result: dict[str, Any],
    price: float | None,
    rpc_url: str | None,
    private_key: str | None,
) -> None:
    """Persist fill to trades log + trader.json; update spot anchors."""
    from bds_agent.guard_trade_sync import record_guard_fill

    act = result.get("action") or action
    if isinstance(act, str):
        record_guard_fill(
            profile=cfg.profile,
            pool=pool,
            size_usd=cfg.size_usd,
            dry_run=cfg.dry_run,
            guard_state=state,
            action=act,
            result=result,
            price=price,
            rpc_url=rpc_url,
            private_key=private_key,
        )
    if guard_pricing_mode(cfg) == "spot" and isinstance(act, str):
        _record_spot_reference(state, action=act, price=price)
    new_pos = result.get("new_position")
    if new_pos == "reserve":
        state["reserve_since"] = utc_now_iso()
    elif new_pos == "token":
        state.pop("reserve_since", None)


def _record_spot_reference(
    state: dict[str, Any],
    *,
    action: str,
    price: float | None,
) -> None:
    if price is None or price <= 0:
        return
    if action in ("take_profit_sell", "stop_loss_sell"):
        state["last_exit_usd"] = price
    elif action in ("reentry_buy_dip", "reentry_buy_breakout", "initial_entry_buy"):
        state["reference_entry_usd"] = price
        state["last_exit_usd"] = None


def _sync_guard_config_state(
    state: dict[str, Any],
    *,
    pool: WatchedPool,
    base_token: str,
    cfg: GuardConfig,
) -> None:
    state["pool_address"] = pool.address
    state["pool_label"] = pool.label
    state["base_token"] = base_token
    state["pricing_mode"] = guard_pricing_mode(cfg)
    state["take_profit_pct"] = cfg.take_profit_pct
    state["stop_loss_pct"] = cfg.stop_loss_pct
    state["reentry_retrace_pct"] = cfg.reentry_retrace_pct
    state["reserve_max_minutes"] = cfg.reserve_max_minutes
    if guard_pricing_mode(cfg) == "explicit":
        state["threshold_high"] = cfg.threshold_high
        state["threshold_low"] = cfg.threshold_low
    else:
        state.pop("threshold_high", None)
        state.pop("threshold_low", None)


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
    chain_id: int,
) -> dict[str, Any]:
    if cfg.dry_run:
        new_position = "reserve" if action in ("take_profit_sell", "stop_loss_sell") else "token"
        return {
            "dry_run": True,
            "action": action,
            "price_usd": price,
            "new_position": new_position,
        }
    if action in ("take_profit_sell", "stop_loss_sell"):
        from eth_account import Account

        from bds_agent.positions import find_position, normalize_trader_state, position_sell_tokens
        from bds_agent.trader_state import load_trader_state

        owner = Account.from_key(private_key.strip()).address
        wallet_bal = get_erc20_balance_human(
            rpc_url,
            pool.base_token,
            owner,
            pool.base_decimals,
        )
        trader_state = normalize_trader_state(load_trader_state(cfg.profile))
        pos = find_position(trader_state, pool.address)
        sell_amt = position_sell_tokens(
            pos,
            wallet_bal,
            fallback_size_usd=cfg.size_usd,
            fallback_price_usd=price,
        )
        if sell_amt <= 0:
            raise RuntimeError("No base token balance to sell")
        tx = swap_token_to_usdc(
            rpc_url,
            private_key,
            pool,
            sell_amt,
            slippage=cfg.slippage,
            token_price_usd=price,
            chain_id=chain_id,
        )
        return {"action": action, "tx_hash": tx, "new_position": "reserve"}
    if action in ("reentry_buy_dip", "reentry_buy_breakout"):
        tx, spent_usd = swap_usdc_to_token(
            rpc_url,
            private_key,
            pool,
            size_usd=cfg.size_usd,
            slippage=cfg.slippage,
            token_price_usd=price,
            chain_id=chain_id,
        )
        return {
            "action": action,
            "tx_hash": tx,
            "size_usd": spent_usd,
            "new_position": "token",
        }
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
    chain_id: int,
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
    tx, spent_usd = swap_usdc_to_token(
        rpc_url,
        private_key,
        pool,
        size_usd=cfg.size_usd,
        slippage=cfg.slippage,
        token_price_usd=price,
        chain_id=chain_id,
    )
    return {
        "action": "initial_entry_buy",
        "tx_hash": tx,
        "size_usd": spent_usd,
        "price_usd": price,
        "new_position": "token",
    }


def run_initial_entry_if_needed(
    cfg: GuardConfig,
    pool: WatchedPool,
    *,
    position: Position,
    price: float | None,
    rpc_url: str | None,
    private_key: str | None,
    chain_id: int,
    allow_reserve_enter: bool = False,
) -> tuple[Position, dict[str, Any] | None]:
    """
    On ``--enter``, swap USDC → base when wallet has negligible base balance.

    Returns updated position (``token`` after a buy) and optional result dict.
    """
    from eth_account import Account
    from bds_agent.evm_tx import wait_for_no_pending_txs
    from bds_agent.evm_swap import _web3

    if not cfg.enter:
        return position, None
    if position == "reserve" and not allow_reserve_enter:
        return position, {
            "skipped": True,
            "reason": "position is reserve — wait for dip/breakout re-entry band",
        }
    if price is None or price <= 0:
        raise RuntimeError(
            "--enter requires a BDS USD price for sizing the USDC → base swap; "
            "price unavailable on startup",
        )
    if cfg.dry_run:
        result = execute_initial_entry(
            cfg,
            pool,
            price=price,
            base_balance_human=0.0,
            rpc_url=rpc_url or "",
            private_key=private_key or "",
            chain_id=chain_id,
        )
        new_pos = result.get("new_position", "token")
        if new_pos in ("token", "reserve"):
            position = new_pos
        return position, result
    if not private_key or not rpc_url:
        raise RuntimeError(
            "Live --enter requires trade wallet. Run: bds-agent trade setup-evm",
        )
    owner = Account.from_key(private_key.strip()).address
    w3 = _web3(rpc_url)
    wait_for_no_pending_txs(w3, owner, timeout=120.0)
    base_bal = get_erc20_balance_human(
        rpc_url,
        pool.base_token,
        owner,
        pool.base_decimals,
    )
    usdc_bal = get_erc20_balance_human(
        rpc_url,
        pool.usdc_token,
        owner,
        pool.quote_decimals,
    )
    if not should_initial_entry(cfg, base_bal):
        return position, {
            "skipped": True,
            "reason": f"already hold {base_bal:g} base",
            "base_balance": base_bal,
        }
    if usdc_bal <= 0:
        raise RuntimeError(
            f"No USDC for --enter: wallet has ${usdc_bal:g} USDC",
        )
    result = execute_initial_entry(
        cfg,
        pool,
        price=price,
        base_balance_human=base_bal,
        rpc_url=rpc_url,
        private_key=private_key,
        chain_id=chain_id,
    )
    new_pos = result.get("new_position", "token")
    if new_pos in ("token", "reserve"):
        position = new_pos
    return position, result


def run_guard_sync(cfg: GuardConfig) -> None:
    out: TimestampedConsole = make_tty_console(verbose=cfg.verbose)
    cfg = normalize_guard_config(cfg)
    state = load_guard_state(cfg.profile)
    state, begin_new_leg = prepare_guard_run_state(state, cfg)
    private_key, rpc_url, chain_id = _resolve_guard_evm(cfg)
    pool, base_token = _prepare_guard_pool(cfg, state, rpc_url=rpc_url)
    from bds_agent.evm_swap import get_token_balances_human
    position: Position = state.get("position") if state.get("position") in ("token", "reserve") else "token"
    _sync_guard_config_state(
        state,
        pool=pool,
        base_token=base_token,
        cfg=cfg,
    )
    save_guard_state(state, cfg.profile)

    pool_from_state = not (cfg.pool and str(cfg.pool).strip())
    usdc_bal = 0.0
    wallet_line = "wallet_usdc=n/a wallet_weth=n/a"
    if private_key and rpc_url:
        from eth_account import Account

        owner = Account.from_key(private_key.strip()).address
        usdc_bal, weth_bal = get_token_balances_human(rpc_url, owner)
        wallet_line = f"wallet_usdc=${usdc_bal:g} wallet_weth={weth_bal:g}"
    mode = guard_pricing_mode(cfg)
    bands_note = ""
    if mode == "spot" and state.get("reference_entry_usd"):
        try:
            hi, lo = resolve_guard_bands(cfg, state, position=position)
            bands_note = format_guard_band_log(
                cfg,
                state,
                position=position,
                band_high=hi,
                band_low=lo,
            )
        except RuntimeError:
            bands_note = ""
    elif mode == "explicit":
        bands_note = (
            f" high=[green]{cfg.threshold_high}[/] low=[yellow]{cfg.threshold_low}[/]"
        )
    _print_guard_startup(
        out,
        cfg=cfg,
        pool=pool,
        base_token=base_token,
        position=position,
        mode=mode,
        chain_id=chain_id,
        bands_note=bands_note,
        wallet_line=wallet_line,
        pool_from_state=pool_from_state,
    )
    if (
        cfg.enter
        and private_key
        and rpc_url
        and 0 < usdc_bal < cfg.size_usd * 0.99
    ):
        out.print(
            "[bold yellow]WARN[/] USDC balance "
            f"[red]${usdc_bal:g}[/] < size [yellow]${cfg.size_usd:g}[/] — "
            "entry will spend available USDC (capped to wallet balance)",
        )

    startup_price = _fetch_guard_price_usd(
        cfg, pool, base_token=base_token, out=out,
    )
    allow_reserve_enter = _allow_reserve_enter(
        cfg,
        state,
        position,
        begin_new_leg=begin_new_leg,
    )
    if cfg.enter:
        try:
            position, entry_result = run_initial_entry_if_needed(
                cfg,
                pool,
                position=position,
                price=startup_price,
                rpc_url=rpc_url,
                private_key=private_key,
                chain_id=chain_id,
                allow_reserve_enter=allow_reserve_enter,
            )
        except Exception as exc:
            err_s = str(exc).split("\n", maxsplit=1)[0]
            out.print(
                f"[bold red]ENTER FAIL[/] {err_s} "
                "[dim]— will retry as pending_action[/]",
            )
            state["pending_action"] = "initial_entry_buy"
            state["last_execute_error"] = err_s
            save_guard_state(state, cfg.profile)
        else:
            state["position"] = position
            state["last_action"] = entry_result
            state["last_execute_error"] = None
            state["last_price_usd"] = startup_price
            state["updated_at"] = utc_now_iso()
            if entry_result and not entry_result.get("skipped"):
                state["pending_action"] = None
            save_guard_state(state, cfg.profile)
            out.print(f"[bold green]ENTER[/] {entry_result}")
            if entry_result and not entry_result.get("skipped"):
                state.pop("fresh_leg", None)
                _after_guard_fill(
                    cfg=cfg,
                    pool=pool,
                    state=state,
                    action="initial_entry_buy",
                    result=entry_result,
                    price=startup_price,
                    rpc_url=rpc_url,
                    private_key=private_key,
                )
                save_guard_state(state, cfg.profile)

    ticks = 0
    pool_tag = _guard_pool_tag(cfg, pool)
    idle_note = _reserve_idle_note(cfg, state)
    while True:
        ticks += 1
        sync_reserve_since(state, position)
        if reserve_idle_timed_out(cfg.reserve_max_minutes, state):
            state["guard_exit_reason"] = "reserve_idle_timeout"
            state["updated_at"] = utc_now_iso()
            save_guard_state(state, cfg.profile)
            out.print(
                f"[bold yellow]IDLE EXIT[/] no dip re-entry within "
                f"[cyan]{cfg.reserve_max_minutes:g}[/] min in "
                f"{_guard_position_markup('reserve')} — guard stopped "
                "[dim](orchestrator can start a new run)[/]",
            )
            break
        idle_note = _reserve_idle_note(cfg, state)
        price = _fetch_guard_price_usd(cfg, pool, base_token=base_token, out=out)
        if price is None:
            _print_guard_tick(
                out,
                ticks=ticks,
                pool_tag=pool_tag,
                base_token=base_token,
                price=None,
                position=position,
                band_s="",
                action=None,
                band_err=None,
                idle_note=idle_note,
            )
        else:
            action: str | None = None
            band_high: float | None = None
            band_low: float | None = None
            band_err: str | None = None
            raw_prev = state.get("last_price_usd")
            prev_price = float(raw_prev) if isinstance(raw_prev, (int, float)) else None
            pending = state.get("pending_action")
            if isinstance(pending, str) and pending.strip():
                action = pending.strip()
            else:
                if (
                    guard_pricing_mode(cfg) == "spot"
                    and position == "token"
                    and not state.get("reference_entry_usd")
                    and price > 0
                ):
                    state["reference_entry_usd"] = price
                try:
                    band_high, band_low = resolve_guard_bands(
                        cfg,
                        state,
                        position=position,
                    )
                except RuntimeError as exc:
                    band_err = str(exc).split("\n", maxsplit=1)[0]
                else:
                    action = evaluate_threshold_cross(
                        price=price,
                        prev_price=prev_price,
                        position=position,
                        threshold_high=band_high,
                        threshold_low=band_low,
                        reentry_on_breakout=(
                            cfg.reentry_on_breakout
                            if guard_pricing_mode(cfg) == "explicit"
                            else False
                        ),
                    )
            band_s = ""
            if band_high is not None and band_low is not None:
                band_s = format_guard_band_log(
                    cfg,
                    state,
                    position=position,
                    band_high=band_high,
                    band_low=band_low,
                )
            _print_guard_tick(
                out,
                ticks=ticks,
                pool_tag=pool_tag,
                base_token=base_token,
                price=price,
                position=position,
                band_s=band_s,
                action=action,
                band_err=band_err,
                idle_note=idle_note,
            )
            if action and not band_err:
                pending_retry = (
                    isinstance(state.get("pending_action"), str)
                    and state.get("pending_action") == action
                )
                if pending_retry:
                    fails = int(state.get("pending_fail_count") or 0)
                    wait_s = min(90.0, cfg.poll_seconds * (2 ** min(fails, 5)))
                    out.print(
                        f"[yellow]RETRY[/] pending {_guard_action_markup(action)} "
                        f"[dim](attempt {fails + 1}, backoff {wait_s:.0f}s)[/]",
                    )
                    time.sleep(wait_s)
                out.print(
                    f"[bold yellow]EXEC[/] {_guard_action_markup(action)} "
                    "[dim](on-chain 1–5 min: mempool, approve, swap, confirm)[/]",
                )
                try:
                    if action == "initial_entry_buy":
                        position, result = run_initial_entry_if_needed(
                            cfg,
                            pool,
                            position=position,
                            price=price,
                            rpc_url=rpc_url,
                            private_key=private_key,
                            chain_id=chain_id,
                            allow_reserve_enter=_allow_reserve_enter(
                                cfg,
                                state,
                                position,
                                begin_new_leg=begin_new_leg,
                                pending_initial_entry=pending_retry,
                            ),
                        )
                        if result is None:
                            result = {"skipped": True}
                    else:
                        result = _execute_action(
                            cfg,
                            pool,
                            action,
                            price,
                            rpc_url=rpc_url,
                            private_key=private_key,
                            chain_id=chain_id,
                        )
                except Exception as exc:
                    err_s = str(exc).split("\n", maxsplit=1)[0]
                    out.print(
                        f"[bold red]EXEC FAIL[/] {_guard_action_markup(action)} "
                        f"{err_s} [dim]— retry next poll (STF/slippage widens)[/]",
                    )
                    state["pending_action"] = action
                    state["last_execute_error"] = err_s
                    state["pending_fail_count"] = int(state.get("pending_fail_count") or 0) + 1
                    save_guard_state(state, cfg.profile)
                else:
                    position = result.get("new_position", position)
                    state["position"] = position
                    state["last_action"] = result
                    state["pending_action"] = None
                    state["last_execute_error"] = None
                    state["pending_fail_count"] = 0
                    out.print(f"[bold green]DONE[/] {result}")
                    _after_guard_fill(
                        cfg=cfg,
                        pool=pool,
                        state=state,
                        action=action,
                        result=result,
                        price=price,
                        rpc_url=rpc_url,
                        private_key=private_key,
                    )
            state["last_price_usd"] = price
            state["updated_at"] = utc_now_iso()
            save_guard_state(state, cfg.profile)

        if cfg.max_ticks and ticks >= cfg.max_ticks:
            break
        time.sleep(cfg.poll_seconds)


def _print_spot_status_bands(out: Console, state: dict[str, Any]) -> None:
    """Active spot bands from persisted %% settings (not stale explicit USD levels)."""
    pos = state.get("position")
    if pos not in ("token", "reserve"):
        return
    tp = state.get("take_profit_pct")
    sl = state.get("stop_loss_pct")
    retrace = state.get("reentry_retrace_pct")
    if tp is None and sl is None:
        return
    try:
        cfg = normalize_guard_config(
            GuardConfig(
                take_profit_pct=float(tp) if tp is not None else None,
                stop_loss_pct=float(sl) if sl is not None else None,
                reentry_retrace_pct=float(retrace) if retrace is not None else 0.5,
                enter=False,
            ),
        )
        high, low = resolve_guard_bands(cfg, state, position=pos)
    except RuntimeError as exc:
        out.print(f"  [dim]spot_bands=[/][yellow]{exc}[/]")
        return
    if pos == "token":
        out.print(f"  [dim]spot_tp=[/][green]${high:g}[/]  [dim]spot_stop=[/][yellow]${low:g}[/]")
    else:
        out.print(
            f"  [dim]spot_reentry_below=[/][cyan]${low:g}[/]  "
            f"[dim](breakout block internal)[/]",
        )


def show_guard_status(profile: str | None = None) -> None:
    out = make_tty_console()
    prof = profile or resolve_profile_name() or "(none)"
    state = load_guard_state(profile)
    mode = state.get("pricing_mode") or "spot"
    out.print(f"[bold blue]GUARD STATUS[/] profile [cyan]{prof}[/]")
    keys = (
        "pool_address",
        "pool_label",
        "base_token",
        "pricing_mode",
        "reference_entry_usd",
        "last_exit_usd",
        "take_profit_pct",
        "stop_loss_pct",
        "reentry_retrace_pct",
        "position",
        "last_price_usd",
        "last_action",
        "reserve_since",
        "reserve_max_minutes",
        "guard_exit_reason",
        "updated_at",
    )
    if mode == "explicit":
        keys = (
            *keys[:9],
            "threshold_high",
            "threshold_low",
            *keys[9:],
        )
    for key in keys:
        val = state.get(key)
        out.print(f"  [dim]{key}=[/]{val}")
    if mode == "spot":
        _print_spot_status_bands(out, state)
    if not state.get("pool_address"):
        out.print(
            "  [dim italic]hint: run guard once with --pool <0x…> and --token "
            "<base> (optional) to pin the watched pool[/]",
        )
