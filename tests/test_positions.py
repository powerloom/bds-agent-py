"""Multi-position trader state tests."""

from __future__ import annotations

from datetime import UTC, datetime

from bds_agent.active_markets import WatchedPool
from bds_agent.multi_pool import MultiPoolTracker, PoolEpochResult
from bds_agent.positions import (
    add_position,
    can_enter_pool,
    new_position_record,
    normalize_trader_state,
    open_pool_keys,
    open_positions,
    position_count,
    remove_position,
    set_pool_reentry_cooldown,
)
from bds_agent.pulse import PulseDiagnostics, PulseThresholds
from bds_agent.trader_state import default_trader_state, load_trader_state, save_trader_state


def _pool(addr: str, label: str) -> WatchedPool:
    return WatchedPool(
        address=addr,
        token0="0xUSDC",
        token1="0xTOKEN",
        base_idx=0,
        label=label,
        fee=3000,
        base_decimals=18,
    )


def test_legacy_state_migrates_to_positions() -> None:
    legacy = {
        **default_trader_state(),
        "position": "LONG",
        "entry_pool": "0xpoola",
        "entry_label": "A/USDC",
        "entry_price": 1.0,
        "size_usd": 10.0,
        "entry_tx": "0xabc",
    }
    state = normalize_trader_state(legacy)
    assert position_count(state) == 1
    assert state["position"] == "LONG"
    assert open_positions(state)[0]["entry_pool"] == "0xpoola"


def test_can_enter_multiple_pools_until_max() -> None:
    state = default_trader_state()
    p1 = _pool("0xpoola", "A/USDC")
    state = add_position(
        state,
        new_position_record(p1, price=1.0, epoch_i=1, size_usd=10.0, entry_tx="tx1"),
    )
    ok, reason = can_enter_pool(state, "0xpoolb", max_open_positions=2, daily_loss_limit_hit=False)
    assert ok is True
    assert reason is None
    ok2, reason2 = can_enter_pool(state, "0xpoola", max_open_positions=2, daily_loss_limit_hit=False)
    assert ok2 is False
    assert reason2 == "already_in_pool"


def test_per_pool_reentry_cooldown() -> None:
    state = default_trader_state()
    now = datetime.now(UTC)
    set_pool_reentry_cooldown(state, "0xpoola", 10.0, now=now)
    ok, reason = can_enter_pool(state, "0xpoola", max_open_positions=5, daily_loss_limit_hit=False)
    assert ok is False
    assert reason == "reentry_cooldown"
    ok, reason = can_enter_pool(state, "0xpoolb", max_open_positions=5, daily_loss_limit_hit=False)
    assert ok is True
    assert reason is None


def test_pick_entry_longs_skips_open_pools() -> None:
    th = PulseThresholds(min_trades=1, cooldown_seconds=0)
    r1 = PoolEpochResult(
        pool=_pool("0xopen", "OPEN/USDC"),
        added=1,
        price=1.0,
        diag=PulseDiagnostics(signal="LONG", price_pct=1.0, burst=3.0, imbalance_pct=50.0),
        signal="LONG",
    )
    r2 = PoolEpochResult(
        pool=_pool("0xnew", "NEW/USDC"),
        added=1,
        price=2.0,
        diag=PulseDiagnostics(signal="LONG", price_pct=2.0, burst=4.0, imbalance_pct=60.0),
        signal="LONG",
    )
    picked = MultiPoolTracker.pick_entry_longs(
        [r1, r2],
        th,
        open_pools={"0xopen"},
        limit=2,
    )
    assert len(picked) == 1
    assert picked[0].pool.address == "0xnew"


def test_pick_entry_longs_blocks_down_spot_move() -> None:
    th = PulseThresholds(min_trades=1, cooldown_seconds=0)
    down = PoolEpochResult(
        pool=_pool("0xdown", "DOWN/USDC"),
        added=1,
        price=1.0,
        diag=PulseDiagnostics(signal="LONG", price_pct=-0.5, burst=3.0, imbalance_pct=50.0),
        signal="LONG",
    )
    up = PoolEpochResult(
        pool=_pool("0xup", "UP/USDC"),
        added=1,
        price=2.0,
        diag=PulseDiagnostics(signal="LONG", price_pct=1.0, burst=3.0, imbalance_pct=50.0),
        signal="LONG",
    )
    picked = MultiPoolTracker.pick_entry_longs(
        [down, up],
        th,
        open_pools=set(),
        limit=2,
        block_long_on_down_move=True,
    )
    assert len(picked) == 1
    assert picked[0].pool.address == "0xup"
    both = MultiPoolTracker.pick_entry_longs(
        [down, up],
        th,
        open_pools=set(),
        limit=2,
        block_long_on_down_move=False,
    )
    assert len(both) == 2


def test_state_roundtrip_with_positions(tmp_path, monkeypatch) -> None:
    from bds_agent import paths

    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path)
    monkeypatch.setenv("BDS_AGENT_PROFILE", "multi")

    p1 = _pool("0xpoola", "A/USDC")
    p2 = _pool("0xpoolb", "B/USDC")
    state = default_trader_state()
    state = add_position(
        state,
        new_position_record(p1, price=1.0, epoch_i=1, size_usd=10.0, entry_tx="tx1"),
    )
    state = add_position(
        state,
        new_position_record(p2, price=2.0, epoch_i=2, size_usd=10.0, entry_tx="tx2"),
    )
    save_trader_state(state, "multi")
    loaded = load_trader_state("multi")
    assert position_count(loaded) == 2
    assert open_pool_keys(loaded) == {"0xpoola", "0xpoolb"}

    loaded = remove_position(loaded, "0xpoola")
    assert position_count(loaded) == 1
    assert "0xpoola" not in open_pool_keys(loaded)
