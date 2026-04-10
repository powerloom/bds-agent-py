from __future__ import annotations

from typing import Any

import httpx

from bds_agent.rules.state import Alert


class DiscordSink:
    type = "discord"

    def __init__(self, webhook_url: str) -> None:
        self._webhook_url = webhook_url.strip()

    @classmethod
    def from_spec(cls, spec: dict[str, Any]) -> DiscordSink:
        url = spec.get("webhook_url")
        if not url or not isinstance(url, str):
            raise ValueError("discord sink requires 'webhook_url'")
        return cls(url)

    async def send(self, alert: Alert) -> None:
        content = f"**{alert.rule}** · epoch `{alert.epoch}` · `{alert.pool_address}`\n{alert.message}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(self._webhook_url, json={"content": content[:2000]})
            r.raise_for_status()
