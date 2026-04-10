from __future__ import annotations

from typing import Any

import httpx

from bds_agent.rules.state import Alert


class SlackSink:
    """Slack Incoming Webhooks: POST JSON ``{\"text\": \"...\"}``."""

    type = "slack"

    def __init__(self, webhook_url: str) -> None:
        self._webhook_url = webhook_url.strip()

    @classmethod
    def from_spec(cls, spec: dict[str, Any]) -> SlackSink:
        url = spec.get("webhook_url")
        if not url or not isinstance(url, str):
            raise ValueError("slack sink requires 'webhook_url'")
        return cls(url)

    async def send(self, alert: Alert) -> None:
        text = f"*{alert.rule}* · epoch `{alert.epoch}` · `{alert.pool_address}`\n{alert.message}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(self._webhook_url, json={"text": text[:4000]})
            r.raise_for_status()
