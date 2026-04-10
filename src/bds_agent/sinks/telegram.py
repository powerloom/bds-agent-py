from __future__ import annotations

from typing import Any

import httpx

from bds_agent.rules.state import Alert


class TelegramSink:
    type = "telegram"

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._url = f"https://api.telegram.org/bot{bot_token.strip()}/sendMessage"
        self._chat_id = chat_id.strip()

    @classmethod
    def from_spec(cls, spec: dict[str, Any]) -> TelegramSink:
        token = spec.get("bot_token")
        chat_id = spec.get("chat_id")
        if not token or not isinstance(token, str):
            raise ValueError("telegram sink requires 'bot_token'")
        if not chat_id or not isinstance(chat_id, str):
            raise ValueError("telegram sink requires 'chat_id'")
        return cls(token, chat_id)

    async def send(self, alert: Alert) -> None:
        text = f"{alert.rule} | epoch {alert.epoch} | {alert.pool_address}\n{alert.message}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                self._url,
                json={"chat_id": self._chat_id, "text": text[:4000]},
            )
            r.raise_for_status()
