"""Sign and broadcast a single ERC-20 `transfer` (web3.py 7.x, generic chain)."""

from __future__ import annotations

import math
from typing import Any

# Minimal ERC-20 transfer
_ERC20_TRANSFER = [
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
]


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


def send_erc20_transfer(
    rpc_url: str,
    private_key: str,
    token_contract: str,
    recipient: str,
    amount_atomic: int,
    chain_id: int,
) -> str:
    from web3 import Web3

    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 120}))
    if not w3.is_connected():
        raise RuntimeError(f"Could not connect to RPC: {rpc_url!r}")
    acct = w3.eth.account.from_key(private_key.strip())
    ch = w3.eth.chain_id
    if ch != chain_id:
        raise RuntimeError(f"RPC chain_id {ch} does not match expected {chain_id}. Check EVM_RPC_URL.")

    token = w3.to_checksum_address(token_contract)
    to_addr = w3.to_checksum_address(recipient)
    contract = w3.eth.contract(address=token, abi=_ERC20_TRANSFER)
    from_addr = acct.address
    base_tx: dict[str, Any] = contract.functions.transfer(
        to_addr,
        int(amount_atomic),
    ).build_transaction(
        {
            "from": from_addr,
            "chainId": chain_id,
            "nonce": w3.eth.get_transaction_count(from_addr),
        },
    )
    try:
        gas = w3.eth.estimate_gas(base_tx)
    except Exception:
        gas = 150_000
    base_tx["gas"] = int(math.ceil(gas * 1.15))
    _fill_fees(w3, base_tx)
    raw = w3.eth.account.sign_transaction(
        base_tx,
        private_key=private_key.strip(),
    )
    h = w3.eth.send_raw_transaction(raw.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(h, timeout=300)
    if receipt["status"] != 1:
        raise RuntimeError("ERC-20 transfer reverted on-chain.")
    return w3.to_hex(h)


NATIVE_VALUE_TOKEN_PLACEHOLDER = "0x0000000000000000000000000000000000000000"


def is_native_value_plan_token(token_contract: str) -> bool:
    """Metering uses all-zero `token_contract` for CGT / native `value` plans (not ERC-20 `transfer`)."""
    t = (token_contract or "").strip().lower()
    return t in (NATIVE_VALUE_TOKEN_PLACEHOLDER.lower(), "0x0")


def send_native_value_transfer(
    rpc_url: str,
    private_key: str,
    recipient: str,
    value_wei: int,
    chain_id: int,
) -> str:
    """Sign and broadcast a simple native `value` send (`to=recipient`, empty input)."""
    from web3 import Web3

    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 120}))
    if not w3.is_connected():
        raise RuntimeError(f"Could not connect to RPC: {rpc_url!r}")
    acct = w3.eth.account.from_key(private_key.strip())
    if w3.eth.chain_id != chain_id:
        raise RuntimeError(f"RPC chain_id {w3.eth.chain_id} does not match expected {chain_id}. Check EVM_RPC_URL.")
    from_addr = acct.address
    to_addr = w3.to_checksum_address(recipient)
    base_tx: dict[str, Any] = {
        "from": from_addr,
        "to": to_addr,
        "value": int(value_wei),
        "chainId": chain_id,
        "nonce": w3.eth.get_transaction_count(from_addr),
    }
    try:
        gas = w3.eth.estimate_gas(base_tx)
    except Exception:
        gas = 21_000
    base_tx["gas"] = int(math.ceil(gas * 1.15))
    _fill_fees(w3, base_tx)
    raw = w3.eth.account.sign_transaction(
        base_tx,
        private_key=private_key.strip(),
    )
    h = w3.eth.send_raw_transaction(raw.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(h, timeout=300)
    if receipt["status"] != 1:
        raise RuntimeError("Native transfer reverted on-chain.")
    return w3.to_hex(h)
