"""Exit strategy evaluation for the Pulse trader (all strategies are optional flags)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass
class ExitCheck:
    name: str
    enabled: bool
    triggered: bool
    detail: str


@dataclass
class ExitConfig:
    """Each strategy can be toggled; first matching rule wins (checked in order below)."""

    signal_reversal: bool = True
    time_based: bool = True
    hold_minutes: float = 10.0
    trailing_stop: bool = True
    trailing_pct: float = 2.0
    take_profit: bool = True
    take_profit_pct: float = 5.0
    stop_loss: bool = True
    stop_loss_pct: float = 2.0


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts or not isinstance(ts, str):
        return None
    s = ts.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def update_peak_price(state: dict[str, Any], current_price: float | None) -> dict[str, Any]:
    """Track highest price seen while LONG (for trailing stop)."""
    if current_price is None or current_price <= 0:
        return state
    peak = state.get("peak_price")
    if peak is None or current_price > float(peak):
        state["peak_price"] = current_price
    return state


def evaluate_exit_checks(
    state: dict[str, Any],
    *,
    current_price: float | None,
    signal: str | None,
    cfg: ExitConfig,
    now: datetime | None = None,
) -> list[ExitCheck]:
    """Describe each exit rule for verbose logging (same order as :func:`check_exit`)."""
    if state.get("position") != "LONG":
        return []

    checks: list[ExitCheck] = []
    entry_price = float(state.get("entry_price") or 0)
    has_price = entry_price > 0 and current_price is not None and current_price > 0
    move_pct: float | None = None
    if has_price:
        move_pct = ((current_price - entry_price) / entry_price) * 100.0

    if cfg.stop_loss:
        if move_pct is None:
            checks.append(ExitCheck("stop_loss", True, False, "no price"))
        else:
            triggered = move_pct <= -cfg.stop_loss_pct
            checks.append(
                ExitCheck(
                    "stop_loss",
                    True,
                    triggered,
                    f"{move_pct:+.2f}% / -{cfg.stop_loss_pct:.1f}%",
                ),
            )
    else:
        checks.append(ExitCheck("stop_loss", False, False, "off"))

    if cfg.take_profit:
        if move_pct is None:
            checks.append(ExitCheck("take_profit", True, False, "no price"))
        else:
            triggered = move_pct >= cfg.take_profit_pct
            checks.append(
                ExitCheck(
                    "take_profit",
                    True,
                    triggered,
                    f"{move_pct:+.2f}% / +{cfg.take_profit_pct:.1f}%",
                ),
            )
    else:
        checks.append(ExitCheck("take_profit", False, False, "off"))

    if cfg.trailing_stop:
        peak = float(state.get("peak_price") or entry_price)
        if not has_price or peak <= 0:
            checks.append(ExitCheck("trailing_stop", True, False, "no price"))
        else:
            drop_from_peak_pct = ((peak - current_price) / peak) * 100.0
            triggered = drop_from_peak_pct >= cfg.trailing_pct
            checks.append(
                ExitCheck(
                    "trailing_stop",
                    True,
                    triggered,
                    f"-{drop_from_peak_pct:.2f}% from peak / -{cfg.trailing_pct:.1f}%",
                ),
            )
    else:
        checks.append(ExitCheck("trailing_stop", False, False, "off"))

    now_dt = now or datetime.now(UTC)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=UTC)
    else:
        now_dt = now_dt.astimezone(UTC)
    if cfg.time_based:
        entry_dt = _parse_iso(state.get("entry_timestamp"))
        if entry_dt is None:
            checks.append(ExitCheck("time_based", True, False, "no entry time"))
        else:
            held_min = (now_dt - entry_dt).total_seconds() / 60.0
            triggered = held_min >= cfg.hold_minutes
            checks.append(
                ExitCheck(
                    "time_based",
                    True,
                    triggered,
                    f"{held_min:.1f}m / {cfg.hold_minutes:.0f}m",
                ),
            )
    else:
        checks.append(ExitCheck("time_based", False, False, "off"))

    if cfg.signal_reversal:
        triggered = signal == "SHORT"
        checks.append(
            ExitCheck(
                "signal_reversal",
                True,
                triggered,
                "SHORT fired" if triggered else "—",
            ),
        )
    else:
        checks.append(ExitCheck("signal_reversal", False, False, "off"))

    return checks


def check_exit(
    state: dict[str, Any],
    *,
    current_price: float | None,
    signal: str | None,
    cfg: ExitConfig,
    now: datetime | None = None,
) -> str | None:
    """
    Return an exit reason string if the open LONG should close, else None.

    Check order (protective exits first):
    stop_loss → take_profit → trailing_stop → time_based → signal_reversal
    """
    for chk in evaluate_exit_checks(
        state,
        current_price=current_price,
        signal=signal,
        cfg=cfg,
        now=now,
    ):
        if chk.enabled and chk.triggered:
            return chk.name
    return None
