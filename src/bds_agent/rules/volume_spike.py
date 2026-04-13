from __future__ import annotations

from typing import Any

from bds_agent.rules.helpers import epoch_swap_volume_usd, norm_pool, parse_rule_float
from bds_agent.rules.state import Alert, RuleState


class VolumeSpikeRule:
    """Alert when epoch swap volume exceeds ``multiplier`` × rolling average over prior epochs."""

    type = "volume_spike"

    def __init__(self, multiplier: float, window_epochs: int) -> None:
        self.multiplier = float(multiplier)
        self.window_epochs = max(1, int(window_epochs))

    @classmethod
    def from_spec(cls, spec: dict[str, Any]) -> VolumeSpikeRule:
        if "multiplier" not in spec:
            raise ValueError("volume_spike requires 'multiplier'")
        win_raw = spec.get("window_epochs", spec.get("window", 10))
        win = int(parse_rule_float(win_raw, allow_km_suffix=False))
        return cls(
            multiplier=parse_rule_float(spec["multiplier"], allow_km_suffix=False),
            window_epochs=max(1, win),
        )

    def evaluate(
        self,
        epoch: int,
        pool: str,
        trades: list[dict[str, Any]],
        state: RuleState,
    ) -> list[Alert]:
        pool_key = norm_pool(pool)
        epoch_volume = epoch_swap_volume_usd(trades)
        alerts: list[Alert] = []
        avg = state.avg_prior_volume(pool_key)
        if avg is not None and avg > 0 and epoch_volume >= self.multiplier * avg:
            alerts.append(
                Alert(
                    rule=self.type,
                    epoch=epoch,
                    pool_address=pool,
                    message=(
                        f"Pool epoch volume ${epoch_volume:,.2f} ≥ "
                        f"{self.multiplier}× rolling avg ${avg:,.2f}"
                    ),
                    details={"epoch_volume": epoch_volume, "rolling_avg": avg},
                ),
            )
        state.record_volume(pool_key, epoch_volume)
        return alerts
