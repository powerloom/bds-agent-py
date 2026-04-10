"""Shared alert and rolling state for rule evaluation."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Alert:
    rule: str
    epoch: int
    pool_address: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


class RuleState:
    """Rolling per-pool volumes for volume-spike detection (and similar windows)."""

    def __init__(self, window: int) -> None:
        self.window = max(1, window)
        self._vol_history: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self.window),
        )

    def record_volume(self, pool: str, epoch_volume: float) -> None:
        self._vol_history[pool].append(epoch_volume)

    def avg_prior_volume(self, pool: str) -> float | None:
        hist = self._vol_history[pool]
        if len(hist) < 2:
            return None
        prev = list(hist)[:-1]
        if not prev:
            return None
        return sum(prev) / len(prev)
