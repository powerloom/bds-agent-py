"""Tests for Threshold Guard logic."""

from __future__ import annotations

from bds_agent.guard import evaluate_threshold_cross


def test_token_take_profit() -> None:
    assert (
        evaluate_threshold_cross(
            price=1.1,
            position="token",
            threshold_high=1.0,
            threshold_low=0.5,
        )
        == "take_profit_sell"
    )


def test_token_stop_loss() -> None:
    assert (
        evaluate_threshold_cross(
            price=0.4,
            position="token",
            threshold_high=1.0,
            threshold_low=0.5,
        )
        == "stop_loss_sell"
    )


def test_reserve_reentry_dip() -> None:
    assert (
        evaluate_threshold_cross(
            price=0.4,
            position="reserve",
            threshold_high=1.0,
            threshold_low=0.5,
        )
        == "reentry_buy_dip"
    )


def test_hold_in_band() -> None:
    assert (
        evaluate_threshold_cross(
            price=0.75,
            position="token",
            threshold_high=1.0,
            threshold_low=0.5,
        )
        is None
    )


def test_reserve_no_reentry_after_take_profit_band() -> None:
    """After selling to USDC, price still above high → hold (no instant buy-back)."""
    assert (
        evaluate_threshold_cross(
            price=1.1,
            position="reserve",
            threshold_high=1.0,
            threshold_low=0.5,
        )
        is None
    )


def test_reserve_reentry_breakout_only_when_opt_in() -> None:
    assert (
        evaluate_threshold_cross(
            price=1.1,
            position="reserve",
            threshold_high=1.0,
            threshold_low=0.5,
            reentry_on_breakout=True,
        )
        == "reentry_buy_breakout"
    )
