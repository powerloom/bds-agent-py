"""Initial USDC → base entry (--enter)."""

from __future__ import annotations

from bds_agent.guard import GuardConfig, should_initial_entry


def test_should_initial_entry_when_flag_and_no_balance() -> None:
    cfg = GuardConfig(threshold_high=1.0, threshold_low=0.5, enter=True)
    assert should_initial_entry(cfg, 0.0) is True


def test_should_not_enter_without_flag() -> None:
    cfg = GuardConfig(threshold_high=1.0, threshold_low=0.5, enter=False)
    assert should_initial_entry(cfg, 0.0) is False


def test_should_skip_enter_when_already_holding_base() -> None:
    cfg = GuardConfig(threshold_high=1.0, threshold_low=0.5, enter=True, enter_min_base=1e-6)
    assert should_initial_entry(cfg, 0.01) is False
