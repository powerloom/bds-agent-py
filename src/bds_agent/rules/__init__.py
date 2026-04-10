"""
Declarative rules over allTrades per-epoch snapshots (``tradeData`` → pools → ``trades``).

Config-driven via a registry: YAML ``type:`` → rule class. Filters (``pool_filter``,
``token_filter``) gate the pool before alert rules run.
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence, runtime_checkable

from bds_agent.rules.min_usd import MinUsdRule
from bds_agent.rules.pool_filter import PoolFilterRule
from bds_agent.rules.price_move import PriceMoveRule
from bds_agent.rules.state import Alert, RuleState
from bds_agent.rules.token_filter import TokenFilterRule
from bds_agent.rules.volume_spike import VolumeSpikeRule


@runtime_checkable
class Rule(Protocol):
    """Evaluate one pool’s swap ``trades`` for a single epoch."""

    type: str

    def evaluate(
        self,
        epoch: int,
        pool: str,
        trades: list[dict[str, Any]],
        state: RuleState,
    ) -> list[Alert]:
        ...


RULE_REGISTRY: dict[str, type] = {
    "min_usd": MinUsdRule,
    "volume_spike": VolumeSpikeRule,
    "price_move": PriceMoveRule,
    "pool_filter": PoolFilterRule,
    "token_filter": TokenFilterRule,
}


def build_rule(spec: dict[str, Any]) -> object:
    """Instantiate a rule from a dict with required ``type`` key."""
    t = spec.get("type")
    if not isinstance(t, str) or not t:
        raise ValueError("rule spec must include non-empty 'type'")
    cls = RULE_REGISTRY.get(t)
    if cls is None:
        raise ValueError(f"unknown rule type: {t!r}")
    if not hasattr(cls, "from_spec"):
        raise ValueError(f"rule {t!r} has no factory")
    return cls.from_spec(spec)


def build_rules(specs: Sequence[dict[str, Any]]) -> list[object]:
    return [build_rule(dict(s)) for s in specs]


def volume_window_for_rules(rules: Sequence[object]) -> int:
    """Rolling window size for :class:`RuleState` (max of all ``volume_spike`` rules)."""
    w = 10
    for r in rules:
        if isinstance(r, VolumeSpikeRule):
            w = max(w, r.window_epochs)
    return w


def _pool_trades(pool_snap: Any) -> list[dict[str, Any]]:
    if not isinstance(pool_snap, dict):
        return []
    raw = pool_snap.get("trades") or []
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict)]


def evaluate_snapshot(
    epoch: int,
    snapshot: dict[str, Any],
    state: RuleState,
    rules: Sequence[object],
) -> list[Alert]:
    """
    Walk ``snapshot['tradeData']`` like legacy ``alert_rules.evaluate_epoch``.

    Applies all ``PoolFilterRule`` / ``TokenFilterRule`` gates; then runs remaining
    rules in ``rules`` order.
    """
    pool_filters = [r for r in rules if isinstance(r, PoolFilterRule)]
    token_filters = [r for r in rules if isinstance(r, TokenFilterRule)]
    alert_rules = [
        r
        for r in rules
        if not isinstance(r, (PoolFilterRule, TokenFilterRule))
    ]

    trade_data = snapshot.get("tradeData") or {}
    if not isinstance(trade_data, dict):
        return []

    alerts: list[Alert] = []
    for pool_raw, pool_snap in trade_data.items():
        pool = str(pool_raw)
        if not all(pf.allows_pool(pool) for pf in pool_filters):
            continue
        trades = _pool_trades(pool_snap)
        if not all(tf.matches_trades(trades) for tf in token_filters):
            continue
        for rule in alert_rules:
            alerts.extend(rule.evaluate(epoch, pool, trades, state))

    return alerts


__all__ = [
    "Alert",
    "RULE_REGISTRY",
    "Rule",
    "RuleState",
    "build_rule",
    "build_rules",
    "evaluate_snapshot",
    "volume_window_for_rules",
    "MinUsdRule",
    "VolumeSpikeRule",
    "PriceMoveRule",
    "PoolFilterRule",
    "TokenFilterRule",
]
