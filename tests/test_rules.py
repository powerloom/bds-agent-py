"""Rules engine: snapshot walk + min_usd + volume spike state."""

from __future__ import annotations

from bds_agent.rules import (
    RuleState,
    build_rules,
    evaluate_snapshot,
    volume_window_for_rules,
)


def _swap(usd: float) -> dict:
    return {
        "tradeType": "Swap",
        "data": {"calculated_trade_amount_usd": usd},
    }


def test_min_usd_triggers() -> None:
    rules = build_rules([{"type": "min_usd", "threshold": 50.0}])
    st = RuleState(10)
    snap = {
        "tradeData": {
            "0xPool1": {
                "trades": [_swap(40.0), _swap(60.0)],
            },
        },
    }
    alerts = evaluate_snapshot(100, snap, st, rules)
    assert len(alerts) == 1
    assert alerts[0].rule == "min_usd"
    assert alerts[0].epoch == 100
    assert "60" in alerts[0].message or "60.00" in alerts[0].message


def test_volume_spike_rolling() -> None:
    rules = build_rules(
        [{"type": "volume_spike", "multiplier": 2.0, "window_epochs": 4}],
    )
    st = RuleState(volume_window_for_rules(rules))
    pool = "0xaaa"
    # Epoch 1: volume 100 → no spike (no history)
    snap1 = {"tradeData": {pool: {"trades": [_swap(100.0)]}}}
    assert evaluate_snapshot(1, snap1, st, rules) == []
    # Epoch 2: volume 100 → avg prior 100, 100 < 2*100
    snap2 = {"tradeData": {pool: {"trades": [_swap(100.0)]}}}
    assert evaluate_snapshot(2, snap2, st, rules) == []
    # Epoch 3: volume 250 → prior avg of [100,100] = 100, 250 >= 200
    snap3 = {"tradeData": {pool: {"trades": [_swap(250.0)]}}}
    out = evaluate_snapshot(3, snap3, st, rules)
    assert len(out) == 1
    assert out[0].rule == "volume_spike"


def test_pool_filter_skips() -> None:
    rules = build_rules(
        [
            {"type": "pool_filter", "pools": ["0xbbb"]},
            {"type": "min_usd", "threshold": 1.0},
        ],
    )
    st = RuleState(10)
    snap = {"tradeData": {"0xaaa": {"trades": [_swap(10.0)]}}}
    assert evaluate_snapshot(1, snap, st, rules) == []
