"""Nonce / pending mempool helpers."""

from __future__ import annotations

from bds_agent.evm_tx import _is_nonce_conflict, pending_tx_count


class _FakeEth:
    def __init__(self, latest: int, pending: int) -> None:
        self._latest = latest
        self._pending = pending

    def get_transaction_count(self, _addr: str, block: str = "latest") -> int:
        if block == "pending":
            return self._pending
        return self._latest


class _FakeW3:
    def __init__(self, latest: int, pending: int) -> None:
        self.eth = _FakeEth(latest, pending)

    def to_checksum_address(self, addr: str) -> str:
        return addr


def test_pending_tx_count() -> None:
    w3 = _FakeW3(latest=5, pending=7)
    assert pending_tx_count(w3, "0xabc") == 2


def test_is_nonce_conflict() -> None:
    assert _is_nonce_conflict(Exception("replacement transaction underpriced"))
    assert not _is_nonce_conflict(Exception("insufficient funds"))
