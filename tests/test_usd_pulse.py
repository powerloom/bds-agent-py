"""Pulse USD price gate tests."""

from __future__ import annotations

from bds_agent.pulse import PulseBuffer, PulseThresholds, evaluate_pulse


def test_usd_price_gate_passes_on_head_tail_move() -> None:
    buf = PulseBuffer(pool_address="0xpool")
    th = PulseThresholds(
        price_move_pct=0.15,
        volume_burst_mult=2.0,
        flow_imbalance_pct=30.0,
        min_trades=1,
        cooldown_seconds=0,
        price_source="usd",
    )
    for epoch in range(100, 120):
        buf.record_usd_price(epoch, 1.0)
    for epoch in range(120, 127):
        buf.record_usd_price(epoch, 1.004)
    # Seed trades for burst/imb gates
    from bds_agent.pulse import NormalizedTrade

    now = 126 * 12
    for i in range(6):
        buf.trades.append(
            NormalizedTrade(
                ts=now - 60 + i,
                usd=1000.0,
                side="buy",
                price=1.0,
                dedupe_key=f"k{i}",
            ),
        )
    diag = evaluate_pulse(buf, th, now_ts=now, now_epoch=126)
    assert diag.price_pct > 0.15
    assert diag.price_ok is True
