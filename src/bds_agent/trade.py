"""Self-contained Pulse trader: BDS stream → signal → Uniswap V3 execution."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from collections.abc import AsyncIterator
from typing import Any

from bds_agent.client import BdsClientError, StreamChunk, stream

from eth_account import Account
from rich.console import Console
from bds_agent.tty_console import format_price_px, make_tty_console
from bds_agent.credentials import load_credentials, resolve_profile_name
from bds_agent.defaults import DEFAULT_BDS_BASE_URL
from bds_agent.trade_config import resolve_trade_wallet
from bds_agent.evm_swap import (
    USDC,
    USDC_WETH_POOL_005,
    get_erc20_balance_human,
    get_token_balances_human,
    swap_token_to_usdc,
    swap_usdc_to_token,
    swap_usdc_to_weth,
    swap_weth_to_usdc,
)
from bds_agent.exit_strategies import ExitCheck, ExitConfig, check_exit, evaluate_exit_checks, update_peak_price
from bds_agent.secrets import redact_secrets
from bds_agent.profile_env import resolve_bds_base_url
from bds_agent.active_markets import WatchedPool, fetch_daily_active_pools
from bds_agent.multi_pool import MultiPoolTracker
from bds_agent.positions import (
    add_position,
    aggregate_position_label,
    can_enter_pool,
    exit_state_view,
    find_position,
    has_open_pool,
    new_position_record,
    normalize_trader_state,
    open_pool_keys,
    open_positions,
    pool_from_position,
    position_count,
    remove_position,
    set_pool_reentry_cooldown,
)
from bds_agent.pulse import PulseBuffer, PulseDiagnostics, PulseThresholds, evaluate_pulse
from bds_agent.trader_state import (
    append_trade,
    calculate_pnl_pct,
    calculate_pnl_usd,
    daily_realized_pnl_usd,
    is_dry_run_position,
    load_trader_state,
    load_trades,
    prepare_live_trader_state,
    save_trader_state,
    set_reentry_cooldown,
    summarize_trades,
    utc_now_iso,
)

STREAM_ENDPOINT = "/mpp/stream/allTrades"


async def _aclose_stream(agen: AsyncIterator[StreamChunk]) -> None:
    """Close SSE async generator so httpx does not keep reading after stop."""
    with contextlib.suppress(BaseException):
        await agen.aclose()


def _trade_shutdown_exc(exc: BaseException) -> bool:
    """True when the operator stopped the trader (Ctrl+C / task cancel)."""
    if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError)):
        return True
    if isinstance(exc, RuntimeError) and "Event loop stopped" in str(exc):
        return True
    return False

PAIR_CONFIG: dict[str, dict[str, str]] = {
    "USDC-WETH": {
        "pool": USDC_WETH_POOL_005,
        "label": "USDC/WETH 0.05%",
    },
}


def _log_timestamp() -> str:
    """UTC prefix for trader stdout (matches trades log ``timestamp`` field style)."""
    from bds_agent.tty_console import log_timestamp

    return log_timestamp()


@dataclass
class TraderConfig:
    pair: str = "USDC-WETH"
    size_usd: float = 25.0
    slippage: float = 0.005
    dry_run: bool = False
    profile: str | None = None
    thresholds: PulseThresholds | None = None
    exit: ExitConfig | None = None
    daily_loss_limit_usd: float = 50.0
    reentry_cooldown_minutes: float = 0.0
    max_open_positions: int = 1
    chain_id: int = 1
    verbose: bool = False
    multi_pool: bool = False
    active_pool_limit: int = 40
    active_interval_seconds: int = 300
    watchlist_refresh_epochs: int = 30
    price_source: str = "trades"
    block_long_on_down_move: bool = True


def _trader_console(*, verbose: bool = False) -> Console:
    return make_tty_console(verbose=verbose)  # type: ignore[return-value]


def _gate_markup(ok: bool) -> str:
    return "[bold green]PASS[/]" if ok else "[red]fail[/]"


def _px_markup(price_pct: float, *, price_ok: bool, has_data: bool) -> str:
    if not has_data:
        return "[dim]—[/]"
    text = f"{price_pct:+.2f}%"
    if price_ok:
        return f"[bold green]{text}[/]"
    if price_pct > 0:
        return f"[yellow]{text}[/]"
    if price_pct < 0:
        return f"[red]{text}[/]"
    return f"[dim]{text}[/]"


def _pos_markup(position: str) -> str:
    if position == "LONG":
        return "[bold green]LONG[/]"
    return "[dim]FLAT[/]"


def _pool_label_markup(label: str, *, is_entry: bool) -> str:
    if not label:
        return ""
    if is_entry:
        return f"[bold magenta]pool={label}[/] "
    return f"[cyan]pool={label}[/] "


def _format_exit_check(chk: ExitCheck) -> str:
    mark = "!" if chk.triggered else "·"
    if chk.triggered:
        style = "bold red"
    elif chk.name in ("take_profit",):
        style = "green"
    elif chk.name in ("stop_loss", "trailing_stop"):
        style = "yellow"
    elif chk.name == "signal_reversal" and chk.detail != "—":
        style = "bold yellow"
    else:
        style = "dim"
    return f"[{style}]{mark}{chk.name}({chk.detail})[/]"


def _format_price_px(price: float | None) -> str:
    return format_price_px(price)


def _verbose_show_exit_checks(
    *,
    position: str,
    pool_address: str,
    open_pools: set[str],
) -> bool:
    """Exit P/L is only meaningful on pools where we are long."""
    if position != "LONG":
        return False
    if not open_pools:
        return True
    return pool_address.lower() in open_pools


def _verbose_short_ignore_reason(
    *,
    signal: str | None,
    position: str,
    pool_address: str,
    open_pools: set[str],
) -> str | None:
    if signal != "SHORT":
        return None
    if position != "LONG":
        return "LONG-only entry"
    if open_pools and pool_address.lower() not in open_pools:
        return "not open pool"
    return None


def _print_verbose_epoch(
    *,
    out: Console,
    epoch_i: int,
    price: float | None,
    added: int,
    diag: PulseDiagnostics,
    thresholds: PulseThresholds,
    state: dict[str, Any],
    cfg: TraderConfig,
    signal: str | None,
    exit_cfg: ExitConfig,
    pool_label: str = "",
    pool_address: str = "",
    open_pools: set[str] | None = None,
) -> None:
    open_pools = open_pools or set()
    is_open = pool_address.lower() in open_pools if open_pools else False
    prefix = _pool_label_markup(pool_label, is_entry=is_open)
    pos = aggregate_position_label(state)
    cool = "[green]ready[/]" if diag.cooled_down else "[yellow]cool[/]"
    px_s = _px_markup(diag.price_pct, price_ok=diag.price_ok, has_data=diag.short_count > 0)
    out.print(
        f"[bold blue]HB[/] {prefix}[dim]epoch=[/][bold]{epoch_i}[/] "
        f"px={px_s} [dim]spot=[/]{_format_price_px(price)} "
        f"[dim]burst=[/][{'green' if diag.burst_ok else 'red'}]{diag.burst:.2f}x[/] "
        f"[dim]imb=[/][{'green' if diag.imbalance_ok else 'red'}]{diag.imbalance_pct:.0f}%[/] "
        f"[dim]n={diag.short_count} added={added} buf={diag.buffer_trades} "
        f"pos={_pos_markup(pos)} {cool} "
        f"gates price={_gate_markup(diag.price_ok)} burst={_gate_markup(diag.burst_ok)} "
        f"imb={_gate_markup(diag.imbalance_ok)}",
    )

    if diag.skip_reason == "warming_up":
        out.print(
            f"  [dim italic]→ warming up[/] [dim](need {thresholds.min_trades} trades in "
            f"{thresholds.window_seconds // 60}m window)[/]",
        )
    elif diag.skip_reason == "no_baseline":
        out.print("  [dim italic]→ no volume baseline yet[/] [dim](1h window empty)[/]")
    elif diag.skip_reason == "cooldown":
        out.print("  [yellow]→ signal cooldown[/] [dim](post-fire)[/]")
    elif diag.skip_reason == "gates_failed":
        failed = [
            name
            for name, ok in (
                ("price", diag.price_ok),
                ("burst", diag.burst_ok),
                ("imb", diag.imbalance_ok),
            )
            if not ok
        ]
        out.print(f"  [yellow]→ gates not met:[/] [red]{', '.join(failed)}[/]")
    elif signal:
        short_ignore = _verbose_short_ignore_reason(
            signal=signal,
            position=pos if pos != "FLAT" else "FLAT",
            pool_address=pool_address,
            open_pools=open_pools,
        )
        if short_ignore:
            out.print(f"  [dim]→ signal [red]SHORT[/] ignored[/] [dim]({short_ignore})[/]")
        elif signal == "LONG":
            out.print("  [bold green]→ signal LONG[/]")
        else:
            out.print("  [bold red]→ signal SHORT[/]")

    if _verbose_show_exit_checks(position=pos if pos != "FLAT" else "FLAT", pool_address=pool_address, open_pools=open_pools):
        pos_row = find_position(state, pool_address) if pool_address else None
        exit_view = exit_state_view(pos_row) if pos_row else state
        exit_checks = evaluate_exit_checks(
            exit_view,
            current_price=price,
            signal=signal,
            cfg=exit_cfg,
        )
        parts = [_format_exit_check(chk) for chk in exit_checks if chk.enabled]
        if parts:
            out.print(f"  [dim]→ exit[/] {' '.join(parts)}")

    if signal == "LONG" and not has_open_pool(state, pool_address):
        down_block = _long_entry_down_move_block(cfg, diag)
        if down_block:
            out.print(f"  [bold yellow]→ entry BLOCKED:[/] [yellow]{down_block}[/]")
        else:
            can_enter, block_reason = _can_enter_pool(cfg, state, pool_address)
            if can_enter:
                out.print("  [bold green]→ entry OK[/]")
            elif block_reason:
                out.print(f"  [bold yellow]→ entry BLOCKED:[/] [yellow]{block_reason}[/]")
            if block_reason == "reentry_cooldown":
                blocked = state.get("pool_reentry_blocked") or {}
                until = blocked.get(pool_address.lower()) or state.get("reentry_blocked_until") or "—"
                out.print(f"  [dim]   until {until}[/]")


def _print_verbose_startup(
    out: Console,
    *,
    cfg: TraderConfig,
    pool: str,
    thresholds: PulseThresholds,
    exit_cfg: ExitConfig,
) -> None:
    out.print(
        f"[bold blue]verbose[/] [dim]thresholds:[/] "
        f"price[dim]≥[/][yellow]{thresholds.price_move_pct}%[/] "
        f"burst[dim]≥[/][yellow]{thresholds.volume_burst_mult}x[/] "
        f"imb[dim]≥[/][yellow]{thresholds.flow_imbalance_pct}%[/] "
        f"window[dim]=[/]{thresholds.window_seconds // 60}m "
        f"min_trades[dim]=[/]{thresholds.min_trades} "
        f"price_src[dim]=[/][cyan]{thresholds.price_source}[/]",
    )
    enabled_exits = [
        name
        for name, on in (
            ("stop_loss", exit_cfg.stop_loss),
            ("take_profit", exit_cfg.take_profit),
            ("trailing_stop", exit_cfg.trailing_stop),
            ("time_based", exit_cfg.time_based),
            ("signal_reversal", exit_cfg.signal_reversal),
        )
        if on
    ]
    exit_list = ", ".join(f"[cyan]{n}[/]" for n in enabled_exits) or "[dim]none[/]"
    out.print(f"[bold blue]verbose[/] [dim]exits (first match):[/] {exit_list}")


def _pool_trades(snapshot: dict[str, Any], pool_address: str) -> list[dict[str, Any]]:
    trade_data = snapshot.get("tradeData") or {}
    if not isinstance(trade_data, dict):
        return []
    key = pool_address.lower()
    for pool_raw, pool_snap in trade_data.items():
        if str(pool_raw).lower() != key:
            continue
        if not isinstance(pool_snap, dict):
            return []
        raw = pool_snap.get("trades") or []
        if not isinstance(raw, list):
            return []
        return [x for x in raw if isinstance(x, dict)]
    return []


def _resolve_wallet() -> tuple[str, str, int]:
    return resolve_trade_wallet()


def _resolve_api_key(profile: str | None) -> str:
    creds = load_credentials()
    if not creds:
        raise RuntimeError("No BDS credentials. Run: bds-agent signup")
    key = creds.get("api_key")
    if not isinstance(key, str) or not key.startswith("sk_live_"):
        raise RuntimeError("Invalid or missing api_key in profile credentials.")
    return key


def _resolve_base_url() -> str:
    bu = resolve_bds_base_url()
    return (bu or DEFAULT_BDS_BASE_URL).rstrip("/")


def _reentry_cooldown_minutes(cfg: TraderConfig) -> float:
    return max(0.0, float(cfg.reentry_cooldown_minutes))


def _daily_loss_limit_hit(cfg: TraderConfig) -> bool:
    pnl = daily_realized_pnl_usd(load_trades(cfg.profile), exclude_dry_run=True)
    return pnl <= -abs(cfg.daily_loss_limit_usd)


def _long_entry_down_move_block(cfg: TraderConfig, diag: PulseDiagnostics) -> str | None:
    """Block LONG when 5m spot window is down (anti dump-chase)."""
    if not cfg.block_long_on_down_move:
        return None
    if diag.price_pct < 0:
        return f"spot move down ({diag.price_pct:+.2f}% / 5m window)"
    return None


def _can_enter_pool(cfg: TraderConfig, state: dict[str, Any], pool: str) -> tuple[bool, str | None]:
    return can_enter_pool(
        state,
        pool,
        max_open_positions=cfg.max_open_positions,
        daily_loss_limit_hit=_daily_loss_limit_hit(cfg),
        use_global_reentry=cfg.max_open_positions <= 1,
    )


def show_status(profile: str | None = None, *, console: Console | None = None) -> None:
    out = console or Console(highlight=False)
    prof = profile or resolve_profile_name() or "(none)"
    state = normalize_trader_state(load_trader_state(profile))
    trades = load_trades(profile)
    daily_pnl = daily_realized_pnl_usd(trades)
    positions = open_positions(state)
    out.print(f"[bold]Profile[/] {prof}")
    label = aggregate_position_label(state)
    if is_dry_run_position(state):
        out.print(f"[bold]Position[/] [cyan]{label}[/] [dim](dry-run — not on-chain)[/]")
    else:
        out.print(f"[bold]Position[/] {label}")
    if positions:
        out.print(f"  open positions: {len(positions)}")
    for i, pos in enumerate(positions, start=1):
        dry = " [dim](dry-run)[/]" if pos.get("dry_run") else ""
        out.print(
            f"  [{i}] {pos.get('entry_label') or '—'} pool={pos.get('entry_pool')} "
            f"entry={pos.get('entry_price')} size=${pos.get('size_usd')}{dry}",
        )
    out.print(f"  daily P/L (UTC): ${daily_pnl:.2f}")
    out.print(f"  usdc_balance (saved): {state.get('usdc_balance')}")
    out.print(f"  weth_balance (saved): {state.get('weth_balance')}")


def show_history(profile: str | None = None, *, console: Console | None = None) -> None:
    out = console or Console(highlight=False)
    trades = load_trades(profile)
    if not trades:
        out.print("[dim]No trades logged yet.[/]")
        return
    for t in trades:
        out.print(str(t))


def show_pnl(profile: str | None = None, *, console: Console | None = None) -> None:
    out = console or Console(highlight=False)
    summary = summarize_trades(load_trades(profile))
    daily = daily_realized_pnl_usd(load_trades(profile))
    out.print(f"Total exits: {summary['total_trades']}")
    out.print(f"Wins: {summary['wins']}  Losses: {summary['losses']}")
    out.print(f"Win rate: {summary['win_rate'] * 100:.1f}%")
    out.print(f"Total P/L: ${summary['total_pnl_usd']:.2f}")
    out.print(f"Today P/L (UTC): ${daily:.2f}")


def _usd_fetcher(
    base_url: str,
    api_key: str,
    *,
    out: Console | None = None,
    abort_on_error: bool = False,
):
    from bds_agent.usd_prices import fetch_token_usd_at_pool
    from bds_agent.secrets import redact_secrets

    def fetch(pool: WatchedPool, epoch: int) -> float | None:
        try:
            return fetch_token_usd_at_pool(
                base_url,
                api_key,
                pool.base_token,
                pool.address,
                epoch,
            )
        except RuntimeError as exc:
            if out is not None:
                out.print(
                    f"[bold red]USD PRICE FAIL[/] {pool.label} epoch={epoch}: "
                    f"{redact_secrets(str(exc))}",
                )
            if abort_on_error:
                raise
            return None

    return fetch


def _position_sell_tokens(
    pos: dict[str, Any],
    cfg: TraderConfig,
    wallet_balance: float,
) -> float:
    """Human base token amount to sell — position record capped by wallet balance."""
    _ = cfg
    if wallet_balance <= 0:
        return 0.0
    recorded = float(pos.get("token_balance") or 0.0)
    if recorded > 0:
        return min(recorded, wallet_balance)
    return wallet_balance


def _execute_exit(
    cfg: TraderConfig,
    state: dict[str, Any],
    pos: dict[str, Any],
    *,
    epoch_i: int,
    exit_price: float,
    reason: str,
    out: Console,
    pk: str = "",
    rpc: str = "",
    wallet: str = "",
    chain_id: int = 1,
) -> dict[str, Any]:
    """Close one LONG, log trade, optional per-pool re-entry cooldown. Returns updated state."""
    entry_price = float(pos.get("entry_price") or 0)
    size_usd = float(pos.get("size_usd") or cfg.size_usd)
    pool_addr = str(pos.get("entry_pool") or "")
    pnl_pct = calculate_pnl_pct(entry_price, exit_price)
    pnl_usd = calculate_pnl_usd(size_usd, pnl_pct)
    ts = utc_now_iso()
    label = pos.get("entry_label") or pool_addr[:10]

    if cfg.dry_run:
        out.print(
            f"[cyan]DRY RUN[/] would EXIT {label} ({reason}) @ {exit_price} "
            f"P/L ${pnl_usd:.2f} ({pnl_pct * 100:.2f}%)",
        )
        append_trade(
            {
                "type": "EXIT",
                "reason": reason,
                "dry_run": True,
                "epoch": epoch_i,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl_usd": pnl_usd,
                "pnl_pct": pnl_pct,
                "pool": pool_addr,
                "label": pos.get("entry_label"),
                "tx": "dry-run",
                "timestamp": ts,
            },
            cfg.profile,
        )
        if not pos.get("dry_run"):
            out.print(
                "[yellow]DRY RUN[/] left live position in trader.json "
                "(on-chain tokens unchanged)",
            )
            return state
    else:
        try:
            pool = pool_from_position(pos)
            if pool is not None and pool.live_swap_ready():
                wallet_bal = get_erc20_balance_human(
                    rpc,
                    pool.base_token,
                    wallet,
                    pool.base_decimals,
                )
                token_bal = _position_sell_tokens(pos, cfg, wallet_bal)
                if token_bal <= 0:
                    out.print(
                        f"[yellow]No on-chain balance[/] for {label} — "
                        "remove position from trader.json or run [cyan]bds-agent trade reconcile[/]",
                    )
                    return state
                tx = swap_token_to_usdc(
                    rpc,
                    pk,
                    pool,
                    token_bal,
                    chain_id=chain_id,
                    slippage=cfg.slippage,
                    token_price_usd=exit_price,
                )
                usdc_bal = get_erc20_balance_human(rpc, USDC, wallet, 6)
            else:
                weth_bal = float(pos.get("token_balance") or state.get("weth_balance") or 0)
                if weth_bal <= 0:
                    _, weth_bal = get_token_balances_human(rpc, wallet)
                tx = swap_weth_to_usdc(
                    rpc,
                    pk,
                    weth_bal,
                    chain_id=chain_id,
                    slippage=cfg.slippage,
                    weth_price_usd=exit_price,
                )
                usdc_bal, _ = get_token_balances_human(rpc, wallet)
        except Exception as exc:
            pos["exit_pending"] = reason
            save_trader_state(state, cfg.profile)
            out.print(
                f"[red]EXIT swap failed[/] {label} ({reason}): {redact_secrets(str(exc))}",
            )
            out.print(
                "[yellow]Position stays OPEN on-chain.[/] "
                "Marked [cyan]exit_pending[/] — next run will retry exit on first tick. "
                "Or [cyan]bds-agent trade exit[/] with higher [cyan]--slippage[/].",
            )
            return state
        append_trade(
            {
                "type": "EXIT",
                "reason": reason,
                "epoch": epoch_i,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl_usd": pnl_usd,
                "pnl_pct": pnl_pct,
                "pool": pool_addr,
                "label": pos.get("entry_label"),
                "tx": tx,
                "timestamp": ts,
            },
            cfg.profile,
        )
        out.print(
            f"[green]EXITED[/] {label} ({reason}) @ {exit_price} P/L ${pnl_usd:.2f} "
            f"({pnl_pct * 100:.2f}%) tx={tx}",
        )
        state = remove_position(state, pool_addr)
        state["usdc_balance"] = usdc_bal
        if cfg.max_open_positions <= 1:
            set_reentry_cooldown(state, _reentry_cooldown_minutes(cfg))
        else:
            set_pool_reentry_cooldown(state, pool_addr, _reentry_cooldown_minutes(cfg))
        save_trader_state(state, cfg.profile)
        return state

    state = remove_position(state, pool_addr)
    if cfg.max_open_positions <= 1:
        set_reentry_cooldown(state, _reentry_cooldown_minutes(cfg))
    else:
        set_pool_reentry_cooldown(state, pool_addr, _reentry_cooldown_minutes(cfg))
    save_trader_state(state, cfg.profile)
    return state


def reconcile_positions(
    cfg: TraderConfig,
    *,
    pool: str | None = None,
    console: Console | None = None,
) -> None:
    """Drop open positions with zero on-chain base token (e.g. after manual swap)."""
    out = console or Console(highlight=False)
    state = normalize_trader_state(load_trader_state(cfg.profile))
    positions = open_positions(state)
    if not positions:
        out.print("[yellow]No open positions.[/]")
        return
    if cfg.dry_run:
        out.print("[yellow]reconcile requires live mode (not --dry-run).[/]")
        return
    pk, rpc, chain_id = _resolve_wallet()
    wallet = Account.from_key(pk).address
    cleared = 0
    for pos in list(positions):
        pool_addr = str(pos.get("entry_pool") or "")
        if pool and pool.strip().lower() != pool_addr.lower():
            continue
        watched = pool_from_position(pos)
        label = pos.get("entry_label") or pool_addr[:10]
        if watched is None:
            continue
        bal = get_erc20_balance_human(
            rpc,
            watched.base_token,
            wallet,
            watched.base_decimals,
        )
        if bal > 0:
            out.print(f"[dim]keep[/] {label} on-chain balance={bal}")
            continue
        state = remove_position(state, pool_addr)
        cleared += 1
        out.print(f"[green]cleared[/] {label} (no on-chain base token)")
    if cleared:
        save_trader_state(state, cfg.profile)
    else:
        out.print("[dim]No zero-balance positions to clear.[/]")


def _market_exit_price(
    pos: dict[str, Any],
    *,
    profile: str | None,
    fallback: float,
    out: Console | None = None,
) -> float:
    """BDS pool USD price for P/L logging; ``fallback`` when fetch fails."""
    watched = pool_from_position(pos)
    if watched is None or fallback <= 0:
        return fallback
    try:
        from bds_agent.usd_prices import fetch_token_usd_at_pool

        px = fetch_token_usd_at_pool(
            _resolve_base_url(),
            _resolve_api_key(profile),
            watched.base_token,
            watched.address,
            None,
        )
        if px is not None and px > 0:
            return float(px)
    except Exception as exc:
        if out is not None:
            out.print(
                f"[yellow]exit price fetch failed[/] {redact_secrets(str(exc))} "
                f"— using entry ${fallback:g}",
            )
    return fallback


def force_exit(
    cfg: TraderConfig,
    *,
    pool: str | None = None,
    console: Console | None = None,
) -> None:
    out = console or Console(highlight=False)
    state = normalize_trader_state(load_trader_state(cfg.profile))
    positions = open_positions(state)
    if not positions:
        out.print("[yellow]No open LONG positions.[/]")
        return
    if pool:
        key = pool.strip().lower()
        positions = [p for p in positions if str(p.get("entry_pool") or "").lower() == key]
        if not positions:
            out.print(f"[yellow]No open position in pool {pool}.[/]")
            return
    pk = rpc = wallet = ""
    chain_id = cfg.chain_id
    if not cfg.dry_run:
        pk, rpc, chain_id = _resolve_wallet()
        wallet = Account.from_key(pk).address
    for pos in positions:
        entry_px = float(pos.get("entry_price") or 0)
        exit_px = _market_exit_price(
            pos,
            profile=cfg.profile,
            fallback=entry_px,
            out=out,
        )
        state = _execute_exit(
            cfg,
            state,
            pos,
            epoch_i=int(pos.get("entry_epoch") or 0),
            exit_price=exit_px,
            reason="manual",
            out=out,
            pk=pk,
            rpc=rpc,
            wallet=wallet,
            chain_id=chain_id,
        )


def _default_usdc_weth_pool() -> WatchedPool:
    return WatchedPool(
        address=USDC_WETH_POOL_005,
        token0=USDC,
        token1="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        base_idx=1,
        label="USDC/WETH",
        frequency=0,
        fee=500,
        base_decimals=18,
    )


def _load_watchlist(cfg: TraderConfig, base_url: str, api_key: str, out: Console) -> list[WatchedPool]:
    try:
        pools = fetch_daily_active_pools(
            base_url,
            api_key,
            time_interval=cfg.active_interval_seconds,
            size=min(cfg.active_pool_limit, 100),
            metadata=True,
        )
    except Exception as exc:
        out.print(f"[yellow]dailyActivePools fetch failed[/] {exc} — using USDC/WETH only")
        pools = []
    pools = pools[: cfg.active_pool_limit]
    if not any(p.address.lower() == USDC_WETH_POOL_005.lower() for p in pools):
        pools.append(_default_usdc_weth_pool())
    if not pools:
        pools = [_default_usdc_weth_pool()]
    return pools


def _enrich_watchlist_for_live(
    pools: list[WatchedPool],
    *,
    rpc_url: str,
    out: Console,
) -> list[WatchedPool]:
    """On-chain fee/decimals before Pulse buffers (avoids inverted base_idx signals)."""
    from bds_agent.evm_swap import enrich_watched_pool_fee

    ready: list[WatchedPool] = []
    for p in pools:
        try:
            ep = enrich_watched_pool_fee(rpc_url, p)
        except Exception as exc:
            out.print(f"[yellow]pool enrich failed[/] {p.label}: {exc}")
            continue
        if ep.live_swap_ready():
            ready.append(ep)
        else:
            out.print(
                f"[yellow]LIVE skip watch[/] {p.label} — missing pool fee/decimals metadata",
            )
    return ready or [_default_usdc_weth_pool()]


def _merge_watchlist_open_positions(
    watchlist: list[WatchedPool],
    state: dict[str, Any],
) -> list[WatchedPool]:
    """Include held pools so exits still get tape after watchlist refresh drops them."""
    by_key = {p.address.lower(): p for p in watchlist}
    for pos in open_positions(state):
        key = str(pos.get("entry_pool") or "").lower()
        if not key or key in by_key:
            continue
        wp = pool_from_position(pos)
        if wp is not None:
            by_key[key] = wp
    return list(by_key.values())


def _execute_entry_live(
    cfg: TraderConfig,
    state: dict[str, Any],
    pool: WatchedPool,
    *,
    rpc: str,
    pk: str,
    wallet: str,
    chain_id: int,
    price: float | None,
    epoch_i: int,
    out: Console,
) -> dict[str, Any] | None:
    from bds_agent.evm_swap import enrich_watched_pool_fee

    pool = enrich_watched_pool_fee(rpc, pool)
    if not pool.live_swap_ready():
        out.print(f"[yellow]LIVE skip[/] {pool.label} — missing pool fee/decimals metadata")
        return None
    token_before = get_erc20_balance_human(rpc, pool.base_token, wallet, pool.base_decimals)
    try:
        tx, spent_usd = swap_usdc_to_token(
            rpc,
            pk,
            pool,
            cfg.size_usd,
            chain_id=chain_id,
            slippage=cfg.slippage,
            token_price_usd=price,
        )
    except Exception as exc:
        out.print(f"[red]ENTRY swap failed[/] {pool.label}: {redact_secrets(str(exc))}")
        out.print(
            "[yellow]No position recorded.[/] "
            "Raise [cyan]--slippage[/] for illiquid pools or wait for calmer tape.",
        )
        return None
    usdc_bal = get_erc20_balance_human(rpc, USDC, wallet, 6)
    token_after = get_erc20_balance_human(rpc, pool.base_token, wallet, pool.base_decimals)
    token_delta = max(0.0, token_after - token_before)
    ts = utc_now_iso()
    pos = new_position_record(
        pool,
        price=price,
        epoch_i=epoch_i,
        size_usd=spent_usd,
        entry_tx=tx,
        token_balance=token_delta or token_after,
        dry_run=False,
        timestamp=ts,
    )
    state = add_position(state, pos)
    state["usdc_balance"] = usdc_bal
    if pool.base_token.lower() == "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2":
        state["weth_balance"] = token_after
    save_trader_state(state, cfg.profile)
    append_trade(
        {
            "type": "ENTRY",
            "direction": "LONG",
            "epoch": epoch_i,
            "price": price,
            "size_usd": spent_usd,
            "pool": pool.address,
            "label": pool.label,
            "tx": tx,
            "timestamp": ts,
        },
        cfg.profile,
    )
    out.print(f"[green]ENTERED LONG[/] {pool.label} @ {price} size=${spent_usd:g} tx={tx}")
    return state


async def _run_multi_pool_trader(cfg: TraderConfig, *, out: Console) -> None:
    api_key = _resolve_api_key(cfg.profile)
    base_url = _resolve_base_url()
    thresholds = cfg.thresholds or PulseThresholds()
    if cfg.price_source:
        thresholds = PulseThresholds(
            **{**thresholds.__dict__, "price_source": cfg.price_source.strip().lower()},
        )
    exit_cfg = cfg.exit or ExitConfig()
    state = normalize_trader_state(load_trader_state(cfg.profile))
    if not cfg.dry_run:
        state, live_notes = prepare_live_trader_state(state, cfg.profile)
        for note in live_notes:
            out.print(f"[yellow]{note}[/]")
        if live_notes:
            save_trader_state(state, cfg.profile)
        for pos in open_positions(state):
            pending = pos.get("exit_pending")
            if pending:
                out.print(
                    f"[yellow]Resuming pending exit[/] {pos.get('entry_label') or pos.get('entry_pool')} "
                    f"({pending}) — will retry when pool price is available",
                )

    watchlist = _load_watchlist(cfg, base_url, api_key, out)

    pk = rpc = ""
    chain_id = cfg.chain_id
    wallet = ""
    if not cfg.dry_run:
        pk, rpc, chain_id = _resolve_wallet()
        wallet = Account.from_key(pk).address
        watchlist = _enrich_watchlist_for_live(watchlist, rpc_url=rpc, out=out)

    watchlist = _merge_watchlist_open_positions(watchlist, state)
    tracker = MultiPoolTracker(watchlist)
    usd_fetch = (
        _usd_fetcher(base_url, api_key, out=out, abort_on_error=False)
        if thresholds.price_source == "usd"
        else None
    )

    labels = ", ".join(p.label for p in watchlist[:8])
    more = f" +{len(watchlist) - 8}" if len(watchlist) > 8 else ""
    out.print(
        f"[dim]trade[/] mode=multi-pool watching={len(watchlist)} "
        f"({labels}{more}) size=${cfg.size_usd:.2f} max_open={cfg.max_open_positions} "
        f"dry_run={cfg.dry_run} active_interval={cfg.active_interval_seconds}s "
        f"profile={cfg.profile or resolve_profile_name()} verbose={cfg.verbose}",
    )
    if cfg.verbose:
        _print_verbose_startup(
            out,
            cfg=cfg,
            pool=f"{len(watchlist)} pools",
            thresholds=thresholds,
            exit_cfg=exit_cfg,
        )

    daily_limit_logged = False
    epochs_since_refresh = 0

    stream_gen = stream(base_url, STREAM_ENDPOINT, api_key)
    try:
        async for chunk in stream_gen:
            if chunk.credit_balance is not None and chunk.credit_balance <= 0:
                out.print("[yellow]credit balance 0[/] — top up at bds-metering.powerloom.io")

            data = chunk.data
            if data.get("skipped"):
                continue
            if "error" in data and "epoch" not in data:
                out.print(f"[red]stream error[/] {data!r}")
                continue

            epoch = data.get("epoch")
            snapshot = data.get("snapshot")
            if epoch is None or not isinstance(snapshot, dict):
                continue
            try:
                epoch_i = int(epoch)
            except (TypeError, ValueError):
                continue

            epochs_since_refresh += 1
            if epochs_since_refresh >= cfg.watchlist_refresh_epochs:
                epochs_since_refresh = 0
                try:
                    refreshed = _load_watchlist(cfg, base_url, api_key, out)
                    if not cfg.dry_run:
                        refreshed = _enrich_watchlist_for_live(
                            refreshed,
                            rpc_url=rpc,
                            out=out,
                        )
                    tracker.refresh_watchlist(
                        refreshed,
                        keep_pool_keys=open_pool_keys(state),
                    )
                    if cfg.verbose:
                        out.print(f"[dim]watchlist[/] refreshed ({len(refreshed)} USDC pools)")
                except Exception as exc:
                    out.print(f"[yellow]watchlist refresh failed[/] {exc}")

            results = tracker.ingest_snapshot(
                epoch_i,
                snapshot,
                thresholds,
                usd_fetcher=usd_fetch,
            )
            active = sum(1 for r in results if r.added > 0)
            signals = [r for r in results if r.signal]

            state = normalize_trader_state(state)
            open_pools = open_pool_keys(state)
            slots = cfg.max_open_positions - position_count(state)

            if cfg.verbose:
                for r in results:
                    if r.added > 0 or r.signal or r.pool.address.lower() in open_pools:
                        _print_verbose_epoch(
                            out=out,
                            epoch_i=epoch_i,
                            price=r.price,
                            added=r.added,
                            diag=r.diag,
                            thresholds=thresholds,
                            state=state,
                            cfg=cfg,
                            signal=r.signal,
                            exit_cfg=exit_cfg,
                            pool_label=r.pool.label,
                            pool_address=r.pool.address,
                            open_pools=open_pools,
                        )
            elif active > 0 or signals:
                sig_part = f" signals={len(signals)}" if signals else ""
                open_part = f" open={position_count(state)}" if position_count(state) else ""
                out.print(
                    f"[dim]MP[/] epoch={epoch_i} active_pools={active}/{len(watchlist)}"
                    f"{open_part}{sig_part}",
                )

            for r in signals:
                out.print(
                    f"[bold cyan]SIGNAL[/] {r.signal} {r.pool.label} "
                    f"epoch={epoch_i} price={r.price} added={r.added}",
                )

            # EXIT each open position on its pool's tape
            for pos in list(open_positions(state)):
                pool_addr = str(pos.get("entry_pool") or "")
                er = tracker.result_for_pool(results, pool_addr)
                if er is None and pool_addr:
                    buf = tracker.get_buffer(pool_addr)
                    price = buf.current_price() if buf else None
                    signal = None
                elif er is not None:
                    price = er.price
                    signal = er.signal
                else:
                    price = float(pos.get("entry_price") or 0) or None
                    signal = None

                exit_view = update_peak_price(exit_state_view(pos), price)
                pos["peak_price"] = exit_view.get("peak_price")
                save_trader_state(state, cfg.profile)
                exit_reason = check_exit(
                    exit_view,
                    current_price=price,
                    signal=signal,
                    cfg=exit_cfg,
                )
                pending = pos.get("exit_pending")
                if pending:
                    exit_reason = str(pending)
                if exit_reason:
                    exit_price = float(price or pos.get("entry_price") or 0)
                    state = _execute_exit(
                        cfg,
                        state,
                        pos,
                        epoch_i=epoch_i,
                        exit_price=exit_price,
                        reason=exit_reason,
                        out=out,
                        pk=pk,
                        rpc=rpc,
                        wallet=wallet,
                        chain_id=chain_id,
                    )

            # ENTRY — fill open slots with ranked LONGs (skip pools already held)
            if slots > 0:
                candidates = MultiPoolTracker.pick_entry_longs(
                    results,
                    thresholds,
                    open_pools=open_pool_keys(state),
                    limit=slots,
                    block_long_on_down_move=cfg.block_long_on_down_move,
                )
                for r in candidates:
                    can_enter, block_reason = _can_enter_pool(cfg, state, r.pool.address)
                    if not can_enter:
                        if block_reason == "daily_loss_limit" and not daily_limit_logged:
                            out.print(
                                f"[yellow]daily loss limit[/] hit (${cfg.daily_loss_limit_usd:.0f}) — "
                                "no new entries until tomorrow (UTC)",
                            )
                            daily_limit_logged = True
                        continue

                    price = r.price
                    if cfg.dry_run:
                        out.print(
                            f"[cyan]DRY RUN[/] would ENTER LONG {r.pool.label} @ {price} "
                            f"size=${cfg.size_usd} pool={r.pool.address}",
                        )
                        append_trade(
                            {
                                "type": "ENTRY",
                                "direction": "LONG",
                                "dry_run": True,
                                "epoch": epoch_i,
                                "price": price,
                                "size_usd": cfg.size_usd,
                                "pool": r.pool.address,
                                "label": r.pool.label,
                                "token": r.pool.base_token,
                                "timestamp": utc_now_iso(),
                            },
                            cfg.profile,
                        )
                        pos = new_position_record(
                            r.pool,
                            price=price,
                            epoch_i=epoch_i,
                            size_usd=cfg.size_usd,
                            entry_tx="dry-run",
                            dry_run=True,
                        )
                        state = add_position(state, pos)
                        save_trader_state(state, cfg.profile)
                    else:
                        new_state = _execute_entry_live(
                            cfg,
                            state,
                            r.pool,
                            rpc=rpc,
                            pk=pk,
                            wallet=wallet,
                            chain_id=chain_id,
                            price=price,
                            epoch_i=epoch_i,
                            out=out,
                        )
                        if new_state is None:
                            continue
                        state = new_state

    except BdsClientError as e:
        out.print(f"[red]stream failed[/] {e}")
        raise SystemExit(1) from e
    except BaseException as exc:
        if _trade_shutdown_exc(exc):
            out.print("[dim]stopped[/]")
        else:
            raise
    finally:
        await _aclose_stream(stream_gen)


async def run_trader(cfg: TraderConfig, *, console: Console | None = None) -> None:
    out = console or _trader_console(verbose=cfg.verbose)
    if cfg.multi_pool:
        await _run_multi_pool_trader(cfg, out=out)
        return

    pair_cfg = PAIR_CONFIG.get(cfg.pair.upper())
    if not pair_cfg:
        raise RuntimeError(f"Unsupported pair {cfg.pair!r}. Supported: {', '.join(PAIR_CONFIG)}")

    pool = pair_cfg["pool"]
    api_key = _resolve_api_key(cfg.profile)
    base_url = _resolve_base_url()
    thresholds = cfg.thresholds or PulseThresholds()
    if cfg.price_source:
        thresholds = PulseThresholds(
            **{**thresholds.__dict__, "price_source": cfg.price_source.strip().lower()},
        )
    exit_cfg = cfg.exit or ExitConfig()
    buffer = PulseBuffer(pool_address=pool.lower(), base_idx=1)
    state = normalize_trader_state(load_trader_state(cfg.profile))
    if not cfg.dry_run:
        state, live_notes = prepare_live_trader_state(state, cfg.profile)
        for note in live_notes:
            out.print(f"[yellow]{note}[/]")
        if live_notes:
            save_trader_state(state, cfg.profile)
        for pos in open_positions(state):
            pending = pos.get("exit_pending")
            if pending:
                out.print(
                    f"[yellow]Resuming pending exit[/] {pos.get('entry_label') or pos.get('entry_pool')} "
                    f"({pending}) — will retry when pool price is available",
                )
    usd_fetch = (
        _usd_fetcher(base_url, api_key, out=out, abort_on_error=True)
        if thresholds.price_source == "usd"
        else None
    )
    default_pool = _default_usdc_weth_pool()
    weth_pool_key = default_pool.address.lower()

    pk = rpc = ""
    chain_id = cfg.chain_id
    wallet = ""
    if not cfg.dry_run:
        pk, rpc, chain_id = _resolve_wallet()
        wallet = Account.from_key(pk).address

    out.print(
        f"[dim]trade[/] pair={cfg.pair} pool={pool} size=${cfg.size_usd:.2f} "
        f"max_open={cfg.max_open_positions} dry_run={cfg.dry_run} "
        f"daily_loss_limit=${cfg.daily_loss_limit_usd:.0f} "
        f"profile={cfg.profile or resolve_profile_name()} verbose={cfg.verbose}",
    )
    if cfg.verbose:
        _print_verbose_startup(out, cfg=cfg, pool=pool, thresholds=thresholds, exit_cfg=exit_cfg)

    daily_limit_logged = False

    stream_gen = stream(base_url, STREAM_ENDPOINT, api_key)
    try:
        async for chunk in stream_gen:
            if chunk.credit_balance is not None and chunk.credit_balance <= 0:
                out.print("[yellow]credit balance 0[/] — top up at bds-metering.powerloom.io")

            data = chunk.data
            if data.get("skipped"):
                continue
            if "error" in data and "epoch" not in data:
                out.print(f"[red]stream error[/] {data!r}")
                continue

            epoch = data.get("epoch")
            snapshot = data.get("snapshot")
            if epoch is None or not isinstance(snapshot, dict):
                continue
            try:
                epoch_i = int(epoch)
            except (TypeError, ValueError):
                continue

            trades = _pool_trades(snapshot, pool)
            added = buffer.ingest_epoch_trades(epoch_i, trades)
            if usd_fetch is not None and (added > 0 or not buffer.usd_samples):
                usd_px = usd_fetch(default_pool, epoch_i)
                if usd_px is not None:
                    buffer.record_usd_price(epoch_i, usd_px)
            price = buffer.current_price()
            diag = evaluate_pulse(buffer, thresholds)
            signal = diag.signal

            state = normalize_trader_state(state)
            open_pools = open_pool_keys(state)
            weth_pos = find_position(state, weth_pool_key)
            if weth_pos is None:
                lone = open_positions(state)
                if len(lone) == 1:
                    only_key = str(lone[0].get("entry_pool") or "").lower()
                    if only_key == weth_pool_key:
                        weth_pos = lone[0]

            if cfg.verbose:
                _print_verbose_epoch(
                    out=out,
                    epoch_i=epoch_i,
                    price=price,
                    added=added,
                    diag=diag,
                    thresholds=thresholds,
                    state=state,
                    cfg=cfg,
                    signal=signal,
                    exit_cfg=exit_cfg,
                    pool_address=pool,
                    open_pools=open_pools,
                )

            if signal:
                out.print(
                    f"[bold cyan]SIGNAL[/] {signal} epoch={epoch_i} price={price} added={added}",
                )

            if weth_pos is not None:
                exit_view = update_peak_price(exit_state_view(weth_pos), price)
                weth_pos["peak_price"] = exit_view.get("peak_price")
                save_trader_state(state, cfg.profile)
                exit_reason = check_exit(
                    exit_view,
                    current_price=price,
                    signal=signal,
                    cfg=exit_cfg,
                )
                pending = weth_pos.get("exit_pending")
                if pending:
                    exit_reason = str(pending)
                if exit_reason:
                    exit_price = float(price or weth_pos.get("entry_price") or 0)
                    state = _execute_exit(
                        cfg,
                        state,
                        weth_pos,
                        epoch_i=epoch_i,
                        exit_price=exit_price,
                        reason=exit_reason,
                        out=out,
                        pk=pk,
                        rpc=rpc,
                        wallet=wallet,
                        chain_id=chain_id,
                    )

            if signal == "LONG":
                down_block = _long_entry_down_move_block(cfg, diag)
                if down_block:
                    if cfg.verbose:
                        out.print(f"  [bold yellow]→ entry BLOCKED:[/] [yellow]{down_block}[/]")
                    continue
                can_enter, block_reason = _can_enter_pool(cfg, state, weth_pool_key)
                if not can_enter:
                    if block_reason == "daily_loss_limit" and not daily_limit_logged:
                        out.print(
                            f"[yellow]daily loss limit[/] hit (${cfg.daily_loss_limit_usd:.0f}) — "
                            "no new entries until tomorrow (UTC)",
                        )
                        daily_limit_logged = True
                    continue

                if cfg.dry_run:
                    out.print(f"[cyan]DRY RUN[/] would ENTER LONG @ {price} size=${cfg.size_usd}")
                    append_trade(
                        {
                            "type": "ENTRY",
                            "direction": "LONG",
                            "dry_run": True,
                            "epoch": epoch_i,
                            "price": price,
                            "size_usd": cfg.size_usd,
                            "timestamp": utc_now_iso(),
                        },
                        cfg.profile,
                    )
                    pos = new_position_record(
                        default_pool,
                        price=price,
                        epoch_i=epoch_i,
                        size_usd=cfg.size_usd,
                        entry_tx="dry-run",
                        dry_run=True,
                    )
                    state = add_position(state, pos)
                    save_trader_state(state, cfg.profile)
                else:
                    _, weth_before = get_token_balances_human(rpc, wallet)
                    try:
                        tx = swap_usdc_to_weth(
                            rpc,
                            pk,
                            cfg.size_usd,
                            chain_id=chain_id,
                            slippage=cfg.slippage,
                            weth_price_usd=price,
                        )
                    except Exception as exc:
                        out.print(
                            f"[red]ENTRY swap failed[/] USDC/WETH: {redact_secrets(str(exc))}",
                        )
                        out.print(
                            "[yellow]No position recorded.[/] "
                            "Raise [cyan]--slippage[/] or wait for calmer tape.",
                        )
                        continue
                    usdc_bal, weth_bal = get_token_balances_human(rpc, wallet)
                    weth_delta = max(0.0, weth_bal - weth_before)
                    ts = utc_now_iso()
                    pos = new_position_record(
                        default_pool,
                        price=price,
                        epoch_i=epoch_i,
                        size_usd=cfg.size_usd,
                        entry_tx=tx,
                        token_balance=weth_delta or weth_bal,
                        dry_run=False,
                        timestamp=ts,
                    )
                    state = add_position(state, pos)
                    state["usdc_balance"] = usdc_bal
                    state["weth_balance"] = weth_bal
                    save_trader_state(state, cfg.profile)
                    append_trade(
                        {
                            "type": "ENTRY",
                            "direction": "LONG",
                            "epoch": epoch_i,
                            "price": price,
                            "size_usd": cfg.size_usd,
                            "tx": tx,
                            "timestamp": ts,
                        },
                        cfg.profile,
                    )
                    out.print(f"[green]ENTERED LONG[/] @ {price} tx={tx}")

    except BdsClientError as e:
        out.print(f"[red]stream failed[/] {e}")
        raise SystemExit(1) from e
    except BaseException as exc:
        if _trade_shutdown_exc(exc):
            out.print("[dim]stopped[/]")
        else:
            raise
    finally:
        await _aclose_stream(stream_gen)


def run_trader_sync(cfg: TraderConfig, *, console: Console | None = None) -> None:
    try:
        asyncio.run(run_trader(cfg, console=console))
    except (KeyboardInterrupt, asyncio.CancelledError):
        return
    except SystemExit:
        raise
    except Exception as exc:
        raise RuntimeError(redact_secrets(str(exc))) from None
