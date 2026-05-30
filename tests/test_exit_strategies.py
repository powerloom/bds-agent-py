"""Exit strategy and risk control tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bds_agent.exit_strategies import ExitConfig, _parse_iso, check_exit, update_peak_price
from bds_agent.trader_state import (
    daily_realized_pnl_usd,
    is_reentry_blocked,
    set_reentry_cooldown,
)


def _long_state(entry_price: float = 3000.0, *, entry_ts: str | None = None) -> dict:
    return {
        "position": "LONG",
        "entry_price": entry_price,
        "peak_price": entry_price,
        "entry_timestamp": entry_ts or "2026-05-20T12:00:00Z",
    }


def test_stop_loss_triggers() -> None:
    cfg = ExitConfig(stop_loss=True, stop_loss_pct=2.0, time_based=False, signal_reversal=False)
    state = _long_state(3000.0)
    # 2% down from 3000 = 2940
    reason = check_exit(state, current_price=2930.0, signal=None, cfg=cfg)
    assert reason == "stop_loss"


def test_take_profit_triggers() -> None:
    cfg = ExitConfig(
        stop_loss=False,
        take_profit=True,
        take_profit_pct=5.0,
        time_based=False,
        signal_reversal=False,
    )
    state = _long_state(3000.0)
    reason = check_exit(state, current_price=3160.0, signal=None, cfg=cfg)
    assert reason == "take_profit"


def test_trailing_stop_triggers() -> None:
    cfg = ExitConfig(
        stop_loss=False,
        take_profit=False,
        trailing_stop=True,
        trailing_pct=2.0,
        time_based=False,
        signal_reversal=False,
    )
    state = _long_state(3000.0)
    state = update_peak_price(state, 3100.0)
    # 2% down from peak 3100 = 3038
    reason = check_exit(state, current_price=3030.0, signal=None, cfg=cfg)
    assert reason == "trailing_stop"


def test_parse_iso_accepts_naive_timestamp() -> None:
    dt = _parse_iso("2026-05-20T12:00:00")
    assert dt is not None
    assert dt.tzinfo is not None
    cfg = ExitConfig(
        stop_loss=False,
        take_profit=False,
        trailing_stop=False,
        time_based=True,
        hold_minutes=10.0,
        signal_reversal=False,
    )
    entry = datetime(2026, 5, 20, 12, 0, 0)
    state = _long_state(entry_ts="2026-05-20T12:00:00")
    now = entry + timedelta(minutes=11)
    reason = check_exit(state, current_price=3000.0, signal=None, cfg=cfg, now=now)
    assert reason == "time_based"


def test_time_based_exit() -> None:
    cfg = ExitConfig(
        stop_loss=False,
        take_profit=False,
        trailing_stop=False,
        time_based=True,
        hold_minutes=10.0,
        signal_reversal=False,
    )
    entry = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)
    state = _long_state(entry_ts=entry.isoformat().replace("+00:00", "Z"))
    now = entry + timedelta(minutes=11)
    reason = check_exit(state, current_price=3000.0, signal=None, cfg=cfg, now=now)
    assert reason == "time_based"


def test_signal_reversal_exit() -> None:
    cfg = ExitConfig(
        stop_loss=False,
        take_profit=False,
        trailing_stop=False,
        time_based=False,
        signal_reversal=True,
    )
    state = _long_state()
    reason = check_exit(state, current_price=3000.0, signal="SHORT", cfg=cfg)
    assert reason == "signal_reversal"


def test_reentry_cooldown() -> None:
    state: dict = {}
    set_reentry_cooldown(state, 10.0, now=datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC))
    assert is_reentry_blocked(state, now=datetime(2026, 5, 20, 12, 5, 0, tzinfo=UTC))
    assert not is_reentry_blocked(state, now=datetime(2026, 5, 20, 12, 11, 0, tzinfo=UTC))


def test_reentry_cooldown_zero_clears_block() -> None:
    state: dict = {"reentry_blocked_until": "2099-01-01T00:00:00Z"}
    set_reentry_cooldown(state, 0.0)
    assert state["reentry_blocked_until"] is None
    assert not is_reentry_blocked(state)


def test_daily_loss_limit_sum() -> None:
    trades = [
        {"type": "EXIT", "pnl_usd": -20.0, "timestamp": "2026-05-20T10:00:00Z"},
        {"type": "EXIT", "pnl_usd": -35.0, "timestamp": "2026-05-20T14:00:00Z"},
        {"type": "EXIT", "pnl_usd": 10.0, "timestamp": "2026-05-19T14:00:00Z"},
    ]
    assert daily_realized_pnl_usd(trades, day="2026-05-20") == -55.0


def test_daily_loss_excludes_dry_run_exits() -> None:
    trades = [
        {"type": "EXIT", "pnl_usd": -50.0, "dry_run": True, "timestamp": "2026-05-20T10:00:00Z"},
        {"type": "EXIT", "pnl_usd": -5.0, "timestamp": "2026-05-20T12:00:00Z"},
    ]
    assert daily_realized_pnl_usd(trades, day="2026-05-20", exclude_dry_run=True) == -5.0
