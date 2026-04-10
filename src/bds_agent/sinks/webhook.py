from __future__ import annotations

import json
from typing import Any

import httpx

from bds_agent.rules.state import Alert


class WebhookSink:
    """POST JSON body with rule, epoch, pool_address, message, details."""

    type = "webhook"

    def __init__(self, url: str) -> None:
        self._url = url.strip()

    @classmethod
    def from_spec(cls, spec: dict[str, Any]) -> WebhookSink:
        url = spec.get("url")
        if not url or not isinstance(url, str):
            raise ValueError("webhook sink requires 'url'")
        return cls(url)

    async def send(self, alert: Alert) -> None:
        payload = {
            "rule": alert.rule,
            "epoch": alert.epoch,
            "pool_address": alert.pool_address,
            "message": alert.message,
            "details": alert.details,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                self._url,
                content=json.dumps(payload, default=str),
                headers={"Content-Type": "application/json"},
            )
            r.raise_for_status()
