"""Trader position state and append-only trade log (per profile)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bds_agent.credentials import resolve_profile_name
from bds_agent.paths import trades_log_path_for_profile, trader_state_path_for_profile


def default_trader_state() -> dict[str, Any]:
    return {
        "positions": [],
        "pool_reentry_blocked": {},
        "position": None,
        "entry_price": None,
        "entry_epoch": None,
        "entry_timestamp": None,
        "entry_tx": None,
        "size_usd": None,
        "peak_price": None,
        "reentry_blocked_until": None,
        "usdc_balance": 0.0,
        "weth_balance": 0.0,
        "token_balance": 0.0,
        "entry_pool": None,
        "entry_label": None,
        "entry_token": None,
        "entry_token0": None,
        "entry_token1": None,
        "entry_base_idx": None,
        "entry_fee": None,
        "entry_base_decimals": None,
        "dry_run_position": False,
    }


def is_dry_run_position(state: dict[str, Any]) -> bool:
    """True when any open LONG exists only from paper trading (no on-chain entry)."""
    from bds_agent.positions import is_dry_run_open, normalize_trader_state

    return is_dry_run_open(normalize_trader_state(state))


def reconcile_live_trader_state(state: dict[str, Any], *, live_mode: bool) -> dict[str, Any]:
    """Drop paper positions when starting a live run; they must not block real entries."""
    if live_mode and is_dry_run_position(state):
        return default_trader_state()
    return state


def last_exit_was_dry_run(profile_name: str | None = None) -> bool:
    exits = [t for t in load_trades(profile_name) if t.get("type") == "EXIT"]
    if not exits:
        return False
    return bool(exits[-1].get("dry_run"))


def prepare_live_trader_state(
    state: dict[str, Any],
    profile_name: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Strip paper-trading artifacts before a live run.

    Returns (state, user-visible notes).
    """
    notes: list[str] = []
    if is_dry_run_position(state):
        state = default_trader_state()
        notes.append(
            "Clearing dry-run position — paper LONG is not on-chain; starting live FLAT",
        )
    elif (
        state.get("position") is None
        and is_reentry_blocked(state)
        and last_exit_was_dry_run(profile_name)
    ):
        state = dict(state)
        state["reentry_blocked_until"] = None
        notes.append(
            "Clearing dry-run re-entry cooldown — paper exit does not block live entries",
        )
    return state, notes


def _profile_or_raise(profile_name: str | None) -> str:
    name = profile_name or resolve_profile_name()
    if not name:
        raise ValueError(
            "No profile selected. Set BDS_AGENT_PROFILE or pass --profile "
            "(run bds-agent signup or credits setup-evm first).",
        )
    return name


def trader_state_path(profile_name: str | None = None) -> Path:
    return trader_state_path_for_profile(_profile_or_raise(profile_name))


def trades_log_path(profile_name: str | None = None) -> Path:
    return trades_log_path_for_profile(_profile_or_raise(profile_name))


def load_trader_state(profile_name: str | None = None) -> dict[str, Any]:
    path = trader_state_path(profile_name)
    if not path.is_file():
        return default_trader_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_trader_state()
    if not isinstance(data, dict):
        return default_trader_state()
    base = default_trader_state()
    base.update(data)
    from bds_agent.positions import normalize_trader_state

    return normalize_trader_state(base)


def save_trader_state(state: dict[str, Any], profile_name: str | None = None) -> Path:
    path = trader_state_path(profile_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return path


def append_trade(trade: dict[str, Any], profile_name: str | None = None) -> None:
    path = trades_log_path(profile_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(trade, separators=(",", ":")) + "\n")


def load_trades(profile_name: str | None = None) -> list[dict[str, Any]]:
    path = trades_log_path(profile_name)
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def calculate_pnl_pct(entry_price: float, exit_price: float, *, direction: str = "LONG") -> float:
    """Return P/L as decimal (0.05 = 5% gain)."""
    if entry_price <= 0:
        return 0.0
    if direction == "LONG":
        return (exit_price - entry_price) / entry_price
    return (entry_price - exit_price) / entry_price


def calculate_pnl_usd(size_usd: float, pnl_pct: float) -> float:
    return size_usd * pnl_pct


def _trade_day_utc(ts: str | None) -> str | None:
    if not ts or not isinstance(ts, str):
        return None
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%d")


def daily_realized_pnl_usd(
    trades: list[dict[str, Any]],
    *,
    day: str | None = None,
) -> float:
    """Sum EXIT pnl_usd for calendar day (UTC). Default: today."""
    target = day or datetime.now(UTC).strftime("%Y-%m-%d")
    total = 0.0
    for t in trades:
        if t.get("type") != "EXIT":
            continue
        d = _trade_day_utc(t.get("timestamp"))
        if d != target:
            continue
        total += float(t.get("pnl_usd") or 0)
    return total


def is_reentry_blocked(state: dict[str, Any], *, now: datetime | None = None) -> bool:
    raw = state.get("reentry_blocked_until")
    if not raw or not isinstance(raw, str):
        return False
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        until = datetime.fromisoformat(s)
    except ValueError:
        return False
    if until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    now_dt = now or datetime.now(UTC)
    return now_dt.astimezone(UTC) < until.astimezone(UTC)


def set_reentry_cooldown(
    state: dict[str, Any],
    cooldown_minutes: float,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if cooldown_minutes <= 0:
        state["reentry_blocked_until"] = None
        return state

    from datetime import timedelta

    now_dt = now or datetime.now(UTC)
    until = now_dt + timedelta(minutes=cooldown_minutes)
    state["reentry_blocked_until"] = until.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return state


def summarize_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    exits = [t for t in trades if t.get("type") == "EXIT"]
    wins = [t for t in exits if float(t.get("pnl_usd") or 0) > 0]
    losses = [t for t in exits if float(t.get("pnl_usd") or 0) < 0]
    total_pnl = sum(float(t.get("pnl_usd") or 0) for t in exits)
    return {
        "total_trades": len(exits),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(exits)) if exits else 0.0,
        "total_pnl_usd": total_pnl,
    }
