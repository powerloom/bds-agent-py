from __future__ import annotations

from typing import Any

from bds_agent.rules.helpers import token_addresses_in_trade_data
from bds_agent.rules.state import Alert, RuleState


class TokenFilterRule:
    """Require at least one swap to touch one of the given token addresses (0x…)."""

    type = "token_filter"

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = frozenset(t.strip().lower() for t in tokens if t)

    @classmethod
    def from_spec(cls, spec: dict[str, Any]) -> TokenFilterRule:
        raw = spec.get("tokens")
        if raw is None:
            return cls(tokens=[])
        if not isinstance(raw, list):
            raise ValueError("token_filter 'tokens' must be a list")
        return cls(tokens=[str(x) for x in raw if x])

    def matches_trades(self, trades: list[dict[str, Any]]) -> bool:
        if not self._tokens:
            return True
        for t in trades:
            if not isinstance(t, dict):
                continue
            addrs = token_addresses_in_trade_data(t)
            if addrs & self._tokens:
                return True
        return False

    def evaluate(
        self,
        epoch: int,
        pool: str,
        trades: list[dict[str, Any]],
        state: RuleState,
    ) -> list[Alert]:
        _ = epoch, pool, trades, state
        return []
