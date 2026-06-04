"""TTY logging: UTC timestamps and Rich markup (guard, pulse trader)."""

from __future__ import annotations

import os
import sys
from typing import Any

from rich.console import Console

from bds_agent.trader_state import utc_now_iso


def log_timestamp() -> str:
    """UTC prefix for stdout (matches trades log ``timestamp`` field)."""
    return utc_now_iso()


class TimestampedConsole:
    """Rich Console wrapper: prefix each ``print`` line with UTC time."""

    def __init__(self, console: Console) -> None:
        self._console = console

    def print(self, *objects: Any, **kwargs: Any) -> None:
        if objects:
            first = objects[0]
            if isinstance(first, str):
                objects = (f"[dim]{log_timestamp()}[/] {first}", *objects[1:])
            else:
                objects = (f"[dim]{log_timestamp()}[/]", *objects)
        else:
            objects = (f"[dim]{log_timestamp()}[/]",)
        self._console.print(*objects, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._console, name)


def make_tty_console(*, verbose: bool = False) -> TimestampedConsole:
    """TTY-aware console with UTC timestamps on every line."""
    no_color = bool(os.environ.get("NO_COLOR"))
    force = bool(os.environ.get("FORCE_COLOR")) or (
        verbose and (sys.stdout.isatty() if sys.stdout else False)
    )
    if not force and (sys.stdout.isatty() if sys.stdout else False):
        force = True
    base = Console(highlight=False, soft_wrap=True, force_terminal=force, no_color=no_color)
    return TimestampedConsole(base)


def format_price_px(price: float | None) -> str:
    if price is None or price <= 0:
        return "—"
    if price >= 100:
        return f"{price:.2f}"
    if price >= 1:
        return f"{price:.4f}"
    if price >= 0.01:
        return f"{price:.6f}"
    return f"{price:.8f}"
