"""Tests for Threshold Guard logic (edge-triggered band crosses)."""

from __future__ import annotations

import pytest

from bds_agent.guard import evaluate_threshold_cross, validate_threshold_brackets


def test_token_take_profit_cross_up() -> None:
    assert (
        evaluate_threshold_cross(
            price=1.1,
            prev_price=0.95,
            position="token",
            threshold_high=1.0,
            threshold_low=0.5,
        )
        == "take_profit_sell"
    )


def test_token_no_take_profit_while_above() -> None:
    """Dwelling above high must not re-fire take-profit."""
    assert (
        evaluate_threshold_cross(
            price=1.1,
            prev_price=1.08,
            position="token",
            threshold_high=1.0,
            threshold_low=0.5,
        )
        is None
    )


def test_token_stop_loss_cross_down() -> None:
    assert (
        evaluate_threshold_cross(
            price=0.4,
            prev_price=0.55,
            position="token",
            threshold_high=1.0,
            threshold_low=0.5,
        )
        == "stop_loss_sell"
    )


def test_token_no_stop_loss_at_2011_when_low_is_2007() -> None:
    assert (
        evaluate_threshold_cross(
            price=2011.45,
            prev_price=2011.40,
            position="token",
            threshold_high=2012.0,
            threshold_low=2007.0,
        )
        is None
    )


def test_reserve_reentry_dip_cross_down() -> None:
    assert (
        evaluate_threshold_cross(
            price=0.4,
            prev_price=0.55,
            position="reserve",
            threshold_high=1.0,
            threshold_low=0.5,
        )
        == "reentry_buy_dip"
    )


def test_reserve_no_reentry_while_below_low() -> None:
    """After stop-loss, dwelling below low must not immediately buy back."""
    assert (
        evaluate_threshold_cross(
            price=2011.45,
            prev_price=2011.50,
            position="reserve",
            threshold_high=2012.0,
            threshold_low=2007.0,
        )
        is None
    )


def test_reserve_no_reentry_above_high_after_take_profit() -> None:
    assert (
        evaluate_threshold_cross(
            price=2012.5,
            prev_price=2012.3,
            position="reserve",
            threshold_high=2012.0,
            threshold_low=2007.0,
        )
        is None
    )


def test_reserve_reentry_breakout_only_when_opt_in() -> None:
    assert (
        evaluate_threshold_cross(
            price=1.1,
            prev_price=0.95,
            position="reserve",
            threshold_high=1.0,
            threshold_low=0.5,
            reentry_on_breakout=True,
        )
        == "reentry_buy_breakout"
    )


def test_hold_in_band() -> None:
    assert (
        evaluate_threshold_cross(
            price=0.75,
            prev_price=0.74,
            position="token",
            threshold_high=1.0,
            threshold_low=0.5,
        )
        is None
    )


def test_first_tick_never_fires() -> None:
    assert (
        evaluate_threshold_cross(
            price=2012.0,
            prev_price=None,
            position="token",
            threshold_high=2012.0,
            threshold_low=2007.0,
        )
        is None
    )


def test_validate_threshold_brackets() -> None:
    validate_threshold_brackets(2012.0, 2007.0)
    with pytest.raises(RuntimeError, match="must be greater"):
        validate_threshold_brackets(2007.0, 2012.0)
