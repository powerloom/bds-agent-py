"""Verbose trade logging helpers."""

from __future__ import annotations

from bds_agent.exit_strategies import ExitCheck
from bds_agent.trade import (
    TimestampedConsole,
    _format_exit_check,
    _format_price_px,
    _gate_markup,
    _log_timestamp,
    _px_markup,
    _verbose_short_ignore_reason,
    _verbose_show_exit_checks,
)
from rich.console import Console


def test_log_timestamp_utc_z_suffix() -> None:
    ts = _log_timestamp()
    assert ts.endswith("Z")
    assert "T" in ts


def test_timestamped_console_prefixes_line() -> None:
    from io import StringIO

    buf = StringIO()
    base = Console(file=buf, force_terminal=True, width=200, no_color=True, highlight=False)
    TimestampedConsole(base).print("HB pool=test")
    line = buf.getvalue()
    assert "Z" in line
    assert "HB pool=test" in line


def test_exit_checks_only_on_open_pools() -> None:
    open_pools = {"0xa"}
    assert _verbose_show_exit_checks(position="FLAT", pool_address="0xA", open_pools=open_pools) is False
    assert _verbose_show_exit_checks(position="LONG", pool_address="0xB", open_pools=open_pools) is False
    assert _verbose_show_exit_checks(position="LONG", pool_address="0xA", open_pools=open_pools) is True
    assert _verbose_show_exit_checks(position="LONG", pool_address="0xA", open_pools=set()) is True


def test_short_ignored_when_flat() -> None:
    assert (
        _verbose_short_ignore_reason(
            signal="SHORT",
            position="FLAT",
            pool_address="0xA",
            open_pools=set(),
        )
        == "LONG-only entry"
    )


def test_short_ignored_on_non_open_pool() -> None:
    assert (
        _verbose_short_ignore_reason(
            signal="SHORT",
            position="LONG",
            pool_address="0xNEAR",
            open_pools={"0xasteroid"},
        )
        == "not open pool"
    )


def test_short_not_ignored_on_open_pool() -> None:
    assert (
        _verbose_short_ignore_reason(
            signal="SHORT",
            position="LONG",
            pool_address="0xASTEROID",
            open_pools={"0xasteroid"},
        )
        is None
    )


def test_gate_markup() -> None:
    assert "green" in _gate_markup(True)
    assert "red" in _gate_markup(False)


def test_px_markup_pass_and_fail() -> None:
    assert "green" in _px_markup(0.3, price_ok=True, has_data=True)
    assert "yellow" in _px_markup(0.1, price_ok=False, has_data=True)
    assert "red" in _px_markup(-0.2, price_ok=False, has_data=True)
    assert "—" in _px_markup(0.0, price_ok=False, has_data=False)


def test_format_price_px_micro_cap() -> None:
    assert _format_price_px(0.00031978) == "0.00031978"
    assert _format_price_px(2120.5) == "2120.50"


def test_format_exit_check_triggered() -> None:
    chk = ExitCheck("stop_loss", True, True, "+3.00% / -2.0%")
    out = _format_exit_check(chk)
    assert "bold red" in out
    assert "!" in out
