from __future__ import annotations

from typing import Any

from rich.console import Console

from bds_agent.rules.state import Alert


class StdoutSink:
    type = "stdout"

    def __init__(self) -> None:
        self._console = Console(highlight=False, soft_wrap=True)

    @classmethod
    def from_spec(cls, spec: dict[str, Any]) -> StdoutSink:
        _ = spec
        return cls()

    async def send(self, alert: Alert) -> None:
        line = (
            f"[bold cyan]{alert.rule}[/] epoch={alert.epoch} pool={alert.pool_address}\n"
            f"{alert.message}"
        )
        self._console.print(line)
