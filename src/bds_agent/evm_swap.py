"""Uniswap V3 SwapRouter swaps and ERC-20 helpers (ETH mainnet)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from bds_agent.evm_tx import (
    pending_nonce,
    send_transaction,
    wait_for_no_pending_txs,
)

if TYPE_CHECKING:
    from bds_agent.active_markets import WatchedPool

SWAP_ROUTER = "0xE592427A0AEce92De3Edee1F18E0157C05861564"
USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
USDC_WETH_POOL_005 = "0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640"
POOL_FEE = 500  # 0.05%

_ERC20_BALANCE = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
]

_ERC20_APPROVE = [
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
]

_SWAP_ROUTER_EXACT_INPUT = [
    {
        "inputs": [
            {
                "components": [
                    {"name": "tokenIn", "type": "address"},
                    {"name": "tokenOut", "type": "address"},
                    {"name": "fee", "type": "uint24"},
                    {"name": "recipient", "type": "address"},
                    {"name": "deadline", "type": "uint256"},
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "amountOutMinimum", "type": "uint256"},
                    {"name": "sqrtPriceLimitX96", "type": "uint160"},
                ],
                "name": "params",
                "type": "tuple",
            }
        ],
        "name": "exactInputSingle",
        "outputs": [{"name": "amountOut", "type": "uint256"}],
        "stateMutability": "payable",
        "type": "function",
    }
]


def _web3(rpc_url: str) -> Any:
    from web3 import Web3

    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 120}))
    if not w3.is_connected():
        raise RuntimeError(f"Could not connect to RPC: {rpc_url!r}")
    return w3


def get_erc20_balance_atomic(
    rpc_url: str,
    token_contract: str,
    owner: str,
) -> int:
    w3 = _web3(rpc_url)
    token = w3.to_checksum_address(token_contract)
    acct = w3.to_checksum_address(owner)
    contract = w3.eth.contract(address=token, abi=_ERC20_BALANCE)
    return int(contract.functions.balanceOf(acct).call())


def get_erc20_balance_human(
    rpc_url: str,
    token_contract: str,
    owner: str,
    decimals: int,
) -> float:
    atomic = get_erc20_balance_atomic(rpc_url, token_contract, owner)
    return atomic / (10**decimals)


def get_token_balances_human(
    rpc_url: str,
    owner: str,
) -> tuple[float, float]:
    """Return (usdc, weth) human-readable balances."""
    usdc_atomic = get_erc20_balance_atomic(rpc_url, USDC, owner)
    weth_atomic = get_erc20_balance_atomic(rpc_url, WETH, owner)
    return usdc_atomic / 1_000_000, weth_atomic / 1e18


def ensure_erc20_allowance(
    rpc_url: str,
    private_key: str,
    token_contract: str,
    spender: str,
    amount_atomic: int,
    chain_id: int,
    *,
    w3: Any | None = None,
    nonce: int | None = None,
    wait_pending: bool = True,
) -> tuple[str | None, int]:
    """
    Approve spender if allowance is insufficient.

    Returns ``(tx_hash_or_none, next_nonce)`` for chaining with a swap on the same ``w3``.
    """
    w3 = w3 or _web3(rpc_url)
    if w3.eth.chain_id != chain_id:
        raise RuntimeError(f"RPC chain_id {w3.eth.chain_id} != expected {chain_id}")
    acct = w3.eth.account.from_key(private_key.strip())
    if wait_pending:
        wait_for_no_pending_txs(w3, acct.address)
    token = w3.to_checksum_address(token_contract)
    spend = w3.to_checksum_address(spender)
    contract = w3.eth.contract(address=token, abi=_ERC20_APPROVE)
    allowance = int(contract.functions.allowance(acct.address, spend).call())
    next_nonce = nonce if nonce is not None else pending_nonce(w3, acct.address)
    if allowance >= amount_atomic:
        return None, next_nonce
    base_tx: dict[str, Any] = contract.functions.approve(
        spend,
        amount_atomic,
    ).build_transaction(
        {
            "from": acct.address,
            "chainId": chain_id,
            "nonce": next_nonce,
        },
    )
    try:
        gas = w3.eth.estimate_gas(base_tx)
    except Exception:
        gas = 100_000
    base_tx["gas"] = int(math.ceil(gas * 1.15))
    tx_hash, next_nonce = send_transaction(
        w3,
        private_key,
        base_tx,
        nonce=next_nonce,
    )
    return tx_hash, next_nonce


def _is_stf_revert(exc: BaseException) -> bool:
    """Uniswap V3 SwapRouter: STF = amountOut below amountOutMinimum."""
    msg = str(exc).upper()
    return "STF" in msg or "SWAP TOO FEW" in msg


def _amount_out_min_attempts(amount_out_min: int) -> list[int]:
    """Relax minimum output on repeated simulation failures (STF)."""
    if amount_out_min <= 0:
        return [0]
    return [
        amount_out_min,
        int(amount_out_min * 0.9),
        int(amount_out_min * 0.75),
        int(amount_out_min * 0.5),
        0,
    ]


def send_uniswap_v3_swap(
    rpc_url: str,
    private_key: str,
    token_in: str,
    token_out: str,
    amount_in: int,
    amount_out_min: int,
    *,
    chain_id: int = 1,
    fee: int = POOL_FEE,
) -> str:
    """Execute Uniswap V3 exactInputSingle; returns tx hash."""
    from web3.exceptions import ContractLogicError

    w3 = _web3(rpc_url)
    if w3.eth.chain_id != chain_id:
        raise RuntimeError(f"RPC chain_id {w3.eth.chain_id} != expected {chain_id}. Check EVM_RPC_URL.")
    acct = w3.eth.account.from_key(private_key.strip())
    router = w3.to_checksum_address(SWAP_ROUTER)
    tin = w3.to_checksum_address(token_in)
    tout = w3.to_checksum_address(token_out)

    _approve_hash, swap_nonce = ensure_erc20_allowance(
        rpc_url,
        private_key,
        token_in,
        router,
        amount_in,
        chain_id,
        w3=w3,
        wait_pending=True,
    )

    import time

    deadline = int(time.time()) + 600
    contract = w3.eth.contract(address=router, abi=_SWAP_ROUTER_EXACT_INPUT)
    last_stf: ContractLogicError | None = None
    nonce = swap_nonce
    for out_min in _amount_out_min_attempts(int(amount_out_min)):
        params = (
            tin,
            tout,
            fee,
            acct.address,
            deadline,
            int(amount_in),
            int(out_min),
            0,
        )
        try:
            base_tx: dict[str, Any] = contract.functions.exactInputSingle(params).build_transaction(
                {
                    "from": acct.address,
                    "chainId": chain_id,
                    "nonce": nonce,
                    "value": 0,
                },
            )
        except ContractLogicError as exc:
            if _is_stf_revert(exc):
                last_stf = exc
                continue
            raise
        try:
            gas = w3.eth.estimate_gas(base_tx)
        except Exception:
            gas = 350_000
        base_tx["gas"] = int(math.ceil(gas * 1.15))
        tx_hash, nonce = send_transaction(
            w3,
            private_key,
            base_tx,
            nonce=nonce,
        )
        return tx_hash
    if last_stf is not None:
        raise last_stf
    raise RuntimeError("Uniswap V3 swap simulation failed.")


def swap_usdc_to_token(
    rpc_url: str,
    private_key: str,
    pool: "WatchedPool",
    size_usd: float,
    *,
    chain_id: int = 1,
    slippage: float = 0.005,
    token_price_usd: float | None = None,
) -> str:
    """Buy base token with USDC via the watched pool's fee tier."""
    if pool.base_idx == 0:
        token_in, token_out = pool.token1, pool.token0
    else:
        token_in, token_out = pool.token0, pool.token1
    amount_in = int(size_usd * (10**pool.quote_decimals))
    amount_out_min = 0
    if token_price_usd and token_price_usd > 0:
        expected = size_usd / token_price_usd
        amount_out_min = int(expected * (10**pool.base_decimals) * (1.0 - slippage))
    return send_uniswap_v3_swap(
        rpc_url,
        private_key,
        token_in,
        token_out,
        amount_in,
        amount_out_min,
        chain_id=chain_id,
        fee=pool.fee,
    )


def _cap_sell_amount_atomic(
    rpc_url: str,
    private_key: str,
    token: str,
    token_amount: float,
    decimals: int,
) -> tuple[int, float]:
    """
    Convert human token amount to wei, capped at on-chain balance.

    Float → int(amt * 10**decimals) can exceed balance by a few wei and cause STF.
    """
    w3 = _web3(rpc_url)
    owner = w3.eth.account.from_key(private_key.strip()).address
    balance_atomic = get_erc20_balance_atomic(rpc_url, token, owner)
    if balance_atomic <= 0:
        return 0, 0.0
    scale = 10**decimals
    desired = int(token_amount * scale)
    amount_in = min(desired, balance_atomic) if desired > 0 else balance_atomic
    effective_human = amount_in / scale
    return amount_in, effective_human


def _slippage_attempts(base_slippage: float) -> list[float]:
    """Widen tolerance for thin pools (meme alts) before relaxing amountOutMinimum."""
    tiers = [
        base_slippage,
        base_slippage * 2.0,
        base_slippage * 4.0,
        min(base_slippage * 8.0, 0.15),
    ]
    out: list[float] = []
    for s in tiers:
        s = min(max(s, 0.0), 0.5)
        if s not in out:
            out.append(s)
    return out


def swap_token_to_usdc(
    rpc_url: str,
    private_key: str,
    pool: "WatchedPool",
    token_amount: float,
    *,
    chain_id: int = 1,
    slippage: float = 0.005,
    token_price_usd: float | None = None,
) -> str:
    """Sell base token for USDC via the watched pool's fee tier."""
    from web3.exceptions import ContractLogicError

    if pool.base_idx == 0:
        token_in, token_out = pool.token0, pool.token1
    else:
        token_in, token_out = pool.token1, pool.token0
    amount_in, sell_human = _cap_sell_amount_atomic(
        rpc_url,
        private_key,
        token_in,
        token_amount,
        pool.base_decimals,
    )
    if amount_in <= 0:
        raise RuntimeError("No base token balance to sell")
    last_err: BaseException | None = None
    for slip in _slippage_attempts(slippage):
        amount_out_min = 0
        if token_price_usd and token_price_usd > 0:
            expected_usdc = sell_human * token_price_usd
            amount_out_min = int(expected_usdc * (10**pool.quote_decimals) * (1.0 - slip))
        try:
            return send_uniswap_v3_swap(
                rpc_url,
                private_key,
                token_in,
                token_out,
                amount_in,
                amount_out_min,
                chain_id=chain_id,
                fee=pool.fee,
            )
        except ContractLogicError as exc:
            last_err = exc
            if not _is_stf_revert(exc):
                raise
    if last_err is not None:
        raise last_err
    raise RuntimeError("swap_token_to_usdc failed")


def swap_usdc_to_weth(
    rpc_url: str,
    private_key: str,
    size_usd: float,
    *,
    chain_id: int = 1,
    slippage: float = 0.005,
    weth_price_usd: float | None = None,
) -> str:
    amount_usdc = int(size_usd * 1_000_000)
    amount_out_min = 0
    if weth_price_usd and weth_price_usd > 0:
        expected_weth = size_usd / weth_price_usd
        amount_out_min = int(expected_weth * 1e18 * (1.0 - slippage))
    return send_uniswap_v3_swap(
        rpc_url,
        private_key,
        USDC,
        WETH,
        amount_usdc,
        amount_out_min,
        chain_id=chain_id,
    )


def swap_weth_to_usdc(
    rpc_url: str,
    private_key: str,
    weth_amount: float,
    *,
    chain_id: int = 1,
    slippage: float = 0.005,
    weth_price_usd: float | None = None,
) -> str:
    amount_weth = int(weth_amount * 1e18)
    amount_out_min = 0
    if weth_price_usd and weth_price_usd > 0:
        expected_usdc = weth_amount * weth_price_usd
        amount_out_min = int(expected_usdc * 1_000_000 * (1.0 - slippage))
    return send_uniswap_v3_swap(
        rpc_url,
        private_key,
        WETH,
        USDC,
        amount_weth,
        amount_out_min,
        chain_id=chain_id,
    )
