from __future__ import annotations

from typing import Any

from bds_agent.rules.helpers import norm_pool
from bds_agent.rules.state import Alert, RuleState


class PoolFilterRule:
    """Restrict evaluation to an allowlist of pools (normalized lowercase hex)."""

    type = "pool_filter"

    def __init__(self, pools: list[str] | None) -> None:
        if pools is None or len(pools) == 0:
            self._allowed: frozenset[str] | None = None
        else:
            self._allowed = frozenset(norm_pool(p) for p in pools if p)

    @classmethod
    def from_spec(cls, spec: dict[str, Any]) -> PoolFilterRule:
        raw = spec.get("pools")
        if raw is None:
            return cls(pools=None)
        if not isinstance(raw, list):
            raise ValueError("pool_filter 'pools' must be a list")
        return cls(pools=[str(x) for x in raw if x])

    def allows_pool(self, pool: str) -> bool:
        if self._allowed is None:
            return True
        return norm_pool(pool) in self._allowed

    def evaluate(
        self,
        epoch: int,
        pool: str,
        trades: list[dict[str, Any]],
        state: RuleState,
    ) -> list[Alert]:
        _ = epoch, pool, trades, state
        return []
