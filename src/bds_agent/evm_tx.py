"""Nonce and broadcast helpers — avoid duplicate nonces and stuck replacements."""

from __future__ import annotations

import time
from typing import Any

def _fill_fees(w3: Any, base_tx: dict[str, Any]) -> None:
    latest = w3.eth.get_block("latest")
    base_fee = latest.get("baseFeePerGas")
    if base_fee is not None:
        try:
            priority = w3.eth.max_priority_fee
        except Exception:
            priority = w3.to_wei(1, "gwei")
        max_fee = int(base_fee) * 2 + int(priority)
        base_tx["maxFeePerGas"] = max_fee
        base_tx["maxPriorityFeePerGas"] = int(priority)
        base_tx["type"] = 2
    else:
        base_tx["gasPrice"] = int(w3.eth.gas_price)
        base_tx["type"] = 0


def pending_nonce(w3: Any, address: str) -> int:
    """Next nonce including mempool (``pending`` block)."""
    addr = w3.to_checksum_address(address)
    return int(w3.eth.get_transaction_count(addr, "pending"))


def confirmed_nonce(w3: Any, address: str) -> int:
    addr = w3.to_checksum_address(address)
    return int(w3.eth.get_transaction_count(addr, "latest"))


def pending_tx_count(w3: Any, address: str) -> int:
    return pending_nonce(w3, address) - confirmed_nonce(w3, address)


def wait_for_no_pending_txs(
    w3: Any,
    address: str,
    *,
    timeout: float = 300.0,
    poll_seconds: float = 3.0,
) -> None:
    """
    Block until pending nonce count matches latest (mempool drained for this wallet).

    Raises if txs are still pending after ``timeout``.
    """
    addr = w3.to_checksum_address(address)
    deadline = time.time() + timeout
    logged_wait = False
    while time.time() < deadline:
        gap = pending_tx_count(w3, addr)
        if gap <= 0:
            return
        if not logged_wait:
            print(
                f"[evm] waiting for {gap} pending tx(s) on {addr[:10]}… "
                f"(up to {int(timeout)}s)",
                flush=True,
            )
            logged_wait = True
        time.sleep(poll_seconds)
    gap = pending_tx_count(w3, addr)
    if gap > 0:
        latest = confirmed_nonce(w3, addr)
        pending = pending_nonce(w3, addr)
        raise RuntimeError(
            f"Wallet {addr} has {gap} pending transaction(s) (nonces {latest}..{pending - 1}). "
            "Wait for them to confirm, speed them up, or cancel them before retrying.",
        )


def _bump_tx_fees(base_tx: dict[str, Any], factor: float) -> None:
    if factor <= 1.0:
        return
    if base_tx.get("type") == 2:
        if "maxFeePerGas" in base_tx:
            base_tx["maxFeePerGas"] = int(int(base_tx["maxFeePerGas"]) * factor)
        if "maxPriorityFeePerGas" in base_tx:
            base_tx["maxPriorityFeePerGas"] = int(
                int(base_tx["maxPriorityFeePerGas"]) * factor,
            )
    elif "gasPrice" in base_tx:
        base_tx["gasPrice"] = int(int(base_tx["gasPrice"]) * factor)


def _is_nonce_conflict(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return (
        "replacement transaction underpriced" in msg
        or "nonce too low" in msg
        or "already known" in msg
    )


def send_transaction(
    w3: Any,
    private_key: str,
    base_tx: dict[str, Any],
    *,
    nonce: int | None = None,
    fee_bump: float = 1.0,
    wait: bool = True,
    receipt_timeout: int = 300,
) -> tuple[str, int]:
    """
    Sign and broadcast ``base_tx``. Returns (tx_hash, next_nonce).

    Uses ``pending`` nonce when ``nonce`` is omitted. On mempool conflicts, bumps
    fees and retries the same nonce up to 3 times.
    """
    from web3.exceptions import Web3RPCError

    acct = w3.eth.account.from_key(private_key.strip())
    n = int(nonce) if nonce is not None else pending_nonce(w3, acct.address)
    tx = dict(base_tx)
    tx["from"] = acct.address
    tx["nonce"] = n
    _bump_tx_fees(tx, fee_bump)
    if "maxFeePerGas" not in tx and "gasPrice" not in tx:
        _fill_fees(w3, tx)

    last_exc: BaseException | None = None
    for attempt in range(4):
        bump = fee_bump * (1.2**attempt) if attempt else fee_bump
        attempt_tx = dict(tx)
        attempt_tx["nonce"] = n
        _bump_tx_fees(attempt_tx, bump)
        if "maxFeePerGas" not in attempt_tx and "gasPrice" not in attempt_tx:
            _fill_fees(w3, attempt_tx)
        try:
            raw = w3.eth.account.sign_transaction(
                attempt_tx,
                private_key=private_key.strip(),
            )
            h = w3.eth.send_raw_transaction(raw.raw_transaction)
            if wait:
                receipt = w3.eth.wait_for_transaction_receipt(h, timeout=receipt_timeout)
                if receipt["status"] != 1:
                    raise RuntimeError("Transaction reverted on-chain.")
            return w3.to_hex(h), n + 1
        except (Web3RPCError, ValueError, OSError) as exc:
            last_exc = exc
            if _is_nonce_conflict(exc) and attempt < 3:
                continue
            raise
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("send_transaction failed without an exception")
