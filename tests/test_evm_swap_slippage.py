"""Swap slippage helpers (no RPC)."""

from __future__ import annotations

from bds_agent.evm_swap import _amount_out_min_attempts, _slippage_attempts
from bds_agent.trade import _position_sell_tokens


def test_float_amount_in_can_exceed_atomic_balance() -> None:
    """Document wei overflow that caused STF on full exits."""
    balance_atomic = 84990239459604278027
    desired = int(84.99023945960428 * 10**18)
    assert desired > balance_atomic


def test_amount_out_min_attempts_relax_to_zero() -> None:
    attempts = _amount_out_min_attempts(10_000_000)
    assert attempts[0] == 10_000_000
    assert attempts[-1] == 0


def test_slippage_attempts_widen() -> None:
    tiers = _slippage_attempts(0.005)
    assert tiers[0] == 0.005
    assert tiers[-1] >= 0.03


def test_position_sell_tokens_sweeps_full_wallet() -> None:
    pos = {
        "token_balance": 86.0,
        "entry_price": 0.174,
        "size_usd": 15.0,
    }
    cfg = type("C", (), {"size_usd": 15.0})()
    assert _position_sell_tokens(pos, cfg, 200.0) == 200.0
    assert _position_sell_tokens(pos, cfg, 50.0) == 50.0
    assert _position_sell_tokens(pos, cfg, 0.0) == 0.0
