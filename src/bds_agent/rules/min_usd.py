from __future__ import annotations

from typing import Any

from bds_agent.rules.helpers import is_swap, parse_rule_float, trade_usd
from bds_agent.rules.state import Alert, RuleState


class MinUsdRule:
    """Alert when any swap in the epoch is at least ``threshold`` USD (largest reported)."""

    type = "min_usd"

    def __init__(self, threshold: float) -> None:
        self.threshold = float(threshold)

    @classmethod
    def from_spec(cls, spec: dict[str, Any]) -> MinUsdRule:
        if "threshold" not in spec:
            raise ValueError("min_usd requires 'threshold'")
        return cls(
            threshold=parse_rule_float(spec["threshold"], allow_km_suffix=True),
        )

    def evaluate(
        self,
        epoch: int,
        pool: str,
        trades: list[dict[str, Any]],
        state: RuleState,
    ) -> list[Alert]:
        _ = state
        pool_display = pool
        best_usd = 0.0
        for t in trades:
            if not isinstance(t, dict) or not is_swap(t):
                continue
            usd = trade_usd(t)
            if usd >= self.threshold:
                best_usd = max(best_usd, usd)
        if best_usd <= 0:
            return []
        return [
            Alert(
                rule=self.type,
                epoch=epoch,
                pool_address=pool_display,
                message=(
                    f"Largest swap ≥ ${self.threshold:,.0f} USD threshold "
                    f"(max ≈ ${best_usd:,.2f} this epoch)"
                ),
                details={"usd": best_usd},
            ),
        ]
