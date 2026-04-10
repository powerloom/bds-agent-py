"""
Alert sinks: async delivery for :class:`bds_agent.rules.state.Alert`.

YAML ``sinks:`` list entries use ``type`` + type-specific keys; see ``docs/SINKS.md``.
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence, runtime_checkable

from bds_agent.rules.state import Alert
from bds_agent.sinks.discord import DiscordSink
from bds_agent.sinks.slack import SlackSink
from bds_agent.sinks.stdout import StdoutSink
from bds_agent.sinks.telegram import TelegramSink
from bds_agent.sinks.webhook import WebhookSink


@runtime_checkable
class AlertSink(Protocol):
    type: str

    async def send(self, alert: Alert) -> None:
        ...


SINK_REGISTRY: dict[str, type] = {
    "stdout": StdoutSink,
    "slack": SlackSink,
    "telegram": TelegramSink,
    "discord": DiscordSink,
    "webhook": WebhookSink,
}


def build_sink(spec: dict[str, Any]) -> AlertSink:
    t = spec.get("type")
    if not isinstance(t, str) or not t:
        raise ValueError("sink spec must include non-empty 'type'")
    cls = SINK_REGISTRY.get(t)
    if cls is None:
        raise ValueError(f"unknown sink type: {t!r}")
    return cls.from_spec(spec)


def build_sinks(specs: Sequence[dict[str, Any]]) -> list[AlertSink]:
    return [build_sink(dict(s)) for s in specs]


async def dispatch_all(sinks: Sequence[AlertSink], alert: Alert) -> None:
    """Send one alert to every sink (sequential)."""
    for s in sinks:
        await s.send(alert)


__all__ = [
    "AlertSink",
    "SINK_REGISTRY",
    "StdoutSink",
    "SlackSink",
    "TelegramSink",
    "DiscordSink",
    "WebhookSink",
    "build_sink",
    "build_sinks",
    "dispatch_all",
]
