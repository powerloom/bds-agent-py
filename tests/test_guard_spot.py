"""Spot-mode guard bands (% from entry / partial giveback after exit)."""

from __future__ import annotations

import pytest

from bds_agent.guard import (
    GuardConfig,
    evaluate_threshold_cross,
    format_guard_band_log,
    normalize_guard_config,
    resolve_guard_bands,
)


def test_spot_take_profit_band() -> None:
    cfg = normalize_guard_config(GuardConfig(take_profit_pct=0.03, enter=True))
    state = {"reference_entry_usd": 2000.0}
    high, low = resolve_guard_bands(cfg, state, position="token")
    assert high == pytest.approx(2060.0)
    assert low == 0.0
    assert (
        evaluate_threshold_cross(
            price=2061.0,
            prev_price=2055.0,
            position="token",
            threshold_high=high,
            threshold_low=low,
        )
        == "take_profit_sell"
    )


def test_spot_reentry_after_half_margin() -> None:
    """Exit 2060 from entry 2000 (+60); re-enter when price crosses down through 2030."""
    cfg = normalize_guard_config(
        GuardConfig(take_profit_pct=0.03, reentry_retrace_pct=0.5, enter=True),
    )
    state = {"reference_entry_usd": 2000.0, "last_exit_usd": 2060.0}
    high, low = resolve_guard_bands(cfg, state, position="reserve")
    assert low == pytest.approx(2030.0)
    assert (
        evaluate_threshold_cross(
            price=2029.0,
            prev_price=2035.0,
            position="reserve",
            threshold_high=high,
            threshold_low=low,
        )
        == "reentry_buy_dip"
    )


def test_spot_no_reentry_while_price_stays_high_after_exit() -> None:
    cfg = normalize_guard_config(GuardConfig(enter=True))
    state = {"reference_entry_usd": 2000.0, "last_exit_usd": 2060.0}
    high, low = resolve_guard_bands(cfg, state, position="reserve")
    assert (
        evaluate_threshold_cross(
            price=2055.0,
            prev_price=2058.0,
            position="reserve",
            threshold_high=high,
            threshold_low=low,
        )
        is None
    )


def test_explicit_mode_requires_both_thresholds() -> None:
    with pytest.raises(RuntimeError, match="both"):
        normalize_guard_config(GuardConfig(threshold_high=2010.0))


def test_spot_stop_loss_band() -> None:
    cfg = normalize_guard_config(
        GuardConfig(take_profit_pct=0.03, stop_loss_pct=0.02, enter=True),
    )
    state = {"reference_entry_usd": 2000.0}
    high, low = resolve_guard_bands(cfg, state, position="token")
    assert high == pytest.approx(2060.0)
    assert low == pytest.approx(1960.0)
    assert (
        evaluate_threshold_cross(
            price=1959.0,
            prev_price=1965.0,
            position="token",
            threshold_high=high,
            threshold_low=low,
        )
        == "stop_loss_sell"
    )


def test_spot_reentry_after_stop_loss_dip_below_exit() -> None:
    """Stop at 1960 from 2000; re-enter when price crosses down through 1940 (cheaper than exit)."""
    cfg = normalize_guard_config(
        GuardConfig(take_profit_pct=0.03, stop_loss_pct=0.02, reentry_retrace_pct=0.5, enter=True),
    )
    state = {"reference_entry_usd": 2000.0, "last_exit_usd": 1960.0}
    high, low = resolve_guard_bands(cfg, state, position="reserve")
    assert low == pytest.approx(1940.0)
    assert (
        evaluate_threshold_cross(
            price=1939.0,
            prev_price=1945.0,
            position="reserve",
            threshold_high=high,
            threshold_low=low,
        )
        == "reentry_buy_dip"
    )


def test_reserve_tick_log_omits_internal_high_band() -> None:
    """After stop_loss_sell, logs must not print the 1e6 breakout sentinel."""
    cfg = normalize_guard_config(
        GuardConfig(take_profit_pct=0.03, stop_loss_pct=0.005, reentry_retrace_pct=0.5, enter=True),
    )
    state = {"reference_entry_usd": 2003.52, "last_exit_usd": 1992.964}
    high, low = resolve_guard_bands(cfg, state, position="reserve")
    assert high > 1e8
    log = format_guard_band_log(
        cfg,
        state,
        position="reserve",
        band_high=high,
        band_low=low,
    )
    assert "e+" not in log and "e-" not in log
    assert "reentry_below=" in log
    assert "last_exit=" in log
    assert "1992.96" in log


def test_stop_loss_pct_must_be_less_than_take_profit() -> None:
    with pytest.raises(RuntimeError, match="less than"):
        normalize_guard_config(
            GuardConfig(take_profit_pct=0.02, stop_loss_pct=0.05, enter=True),
        )


def test_explicit_mode_unchanged() -> None:
    cfg = normalize_guard_config(
        GuardConfig(threshold_high=2012.0, threshold_low=2007.0, enter=False),
    )
    assert cfg.threshold_high == 2012.0
    assert cfg.enter is False
    high, low = resolve_guard_bands(cfg, {}, position="token")
    assert high == 2012.0 and low == 2007.0
