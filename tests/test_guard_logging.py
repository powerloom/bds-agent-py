"""Guard TTY logging (timestamps + Rich markup)."""

from __future__ import annotations

from io import StringIO

from bds_agent.guard import _print_guard_tick
from bds_agent.tty_console import TimestampedConsole
from rich.console import Console


def test_guard_tick_line_has_timestamp_and_no_scientific() -> None:
    buf = StringIO()
    base = Console(file=buf, force_terminal=True, width=200, no_color=True, highlight=False)
    out = TimestampedConsole(base)
    _print_guard_tick(
        out,
        ticks=324,
        pool_tag="USDC/WETH [dim]0xabc[/]",
        base_token="0xC02",
        price=1992.964,
        position="reserve",
        band_s=" [dim]reentry_below=[/][cyan]$1991.46[/]",
        action=None,
        band_err=None,
    )
    line = buf.getvalue()
    assert "Z" in line and "T" in line
    assert "GUARD" in line and "tick=324" in line
    assert "e+" not in line
    assert "hold" in line
    assert "1992.96" in line


def test_startup_reserve_bands_no_scientific_notation() -> None:
    from bds_agent.guard import (
        GuardConfig,
        format_guard_band_log,
        normalize_guard_config,
        resolve_guard_bands,
    )

    cfg = normalize_guard_config(
        GuardConfig(take_profit_pct=0.003, stop_loss_pct=0.002, enter=True),
    )
    state = {
        "reference_entry_usd": 2023.05,
        "last_exit_usd": 2023.05,
        "position": "reserve",
    }
    high, low = resolve_guard_bands(cfg, state, position="reserve")
    assert high > 1e8
    log = format_guard_band_log(
        cfg,
        state,
        position="reserve",
        band_high=high,
        band_low=low,
    )
    assert "e+" not in log and "e-" not in log
    assert "reentry_below=" in log
    assert "last_exit=" in log
