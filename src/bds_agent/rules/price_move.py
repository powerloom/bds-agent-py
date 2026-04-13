from __future__ import annotations

from typing import Any

from bds_agent.rules.helpers import is_swap, parse_rule_float, sqrt_price
from bds_agent.rules.state import Alert, RuleState


class PriceMoveRule:
    """Largest consecutive-swap ``sqrtPriceX96`` move in basis points (proxy for price impact)."""

    type = "price_move"

    def __init__(self, threshold_bps: float) -> None:
        self.threshold_bps = float(threshold_bps)

    @classmethod
    def from_spec(cls, spec: dict[str, Any]) -> PriceMoveRule:
        key = "threshold_bps" if "threshold_bps" in spec else "max_slippage_bps"
        if key not in spec:
            raise ValueError("price_move requires 'threshold_bps' (or legacy 'max_slippage_bps')")
        return cls(
            threshold_bps=parse_rule_float(spec[key], allow_km_suffix=False),
        )

    def evaluate(
        self,
        epoch: int,
        pool: str,
        trades: list[dict[str, Any]],
        state: RuleState,
    ) -> list[Alert]:
        _ = state
        prev_sqrt: int | None = None
        worst_bps = 0.0
        worst_pair: tuple[int, int] | None = None
        for t in trades:
            if not isinstance(t, dict) or not is_swap(t):
                continue
            s = sqrt_price(t)
            if s is None:
                continue
            if prev_sqrt is None:
                prev_sqrt = s
                continue
            if prev_sqrt == 0:
                prev_sqrt = s
                continue
            move_ratio = abs(s - prev_sqrt) / float(prev_sqrt)
            bps = move_ratio * 10_000.0
            if bps > worst_bps:
                worst_bps = bps
                worst_pair = (prev_sqrt, s)
            prev_sqrt = s
        if worst_pair is None or worst_bps < self.threshold_bps:
            return []
        p0, p1 = worst_pair
        return [
            Alert(
                rule=self.type,
                epoch=epoch,
                pool_address=pool,
                message=(
                    f"Largest consecutive-swap sqrtPrice move ≈ {worst_bps:.1f} bps "
                    f"(threshold {self.threshold_bps})"
                ),
                details={"bps": worst_bps, "sqrt_prev": p0, "sqrt_curr": p1},
            ),
        ]
