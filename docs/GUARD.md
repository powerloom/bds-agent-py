# Threshold Guard — `bds-agent guard`

Bracket trades on **one** USDC-quoted pool. Price source: `GET /mpp/token/price/{token}/{pool}` (pool + base token are both required by the API).

## Enter the position (USDC → base)

The guard rail monitors **base token** exposure (e.g. WETH) and sells to USDC on threshold crosses. If your wallet is **USDC-only**, use **`--enter`** so the agent buys the base token before polling:

| Flag | Role |
|------|------|
| **`--enter`** | On start: `swap_usdc_to_token` for **`--size`** USDC if base balance is negligible |
| **`--size`** | USDC notional for entry buy (and for re-entry after a sell) |

One-shot entry without polling:

```bash
bds-agent guard enter --profile bds-tgtest2 \
  --pool 0xE0554a476A092703abdB3Ef35c80e0D76d32939F \
  --token 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2 \
  --size 5
```

Default state assumes **`position=token`** (you are “in” the base leg). Without `--enter`, you must already hold the base token from a prior buy.

**After take-profit** (`position=reserve`): default is **hold USDC** until price **crosses down** through `--threshold-low` (dip re-entry). You will **not** immediately buy back while price is still above `--threshold-high`. Use `--reentry-on-breakout` only if you explicitly want breakout re-entry.

**Edge-triggered (not level):** actions fire only when price **crosses** a band between polls (`prev → current`), not every tick while price sits inside a band. That prevents sell→buy→sell churn. First tick after start never trades (no `prev_price` yet). **`--threshold-high` must be > `--threshold-low`** (e.g. high=2012, low=2007 for WETH).

## Pool + token (price feed)

| Flag | Required | Role |
|------|----------|------|
| `--pool` | First run (then optional) | Uniswap V3 pool; persisted to `.guard.json` |
| `--token` | Optional | Base token for `GET /mpp/token/price/{token}/{pool}` |
| `--threshold-high` / `--threshold-low` | Yes | USD per **1 base token** (e.g. WETH ~2000) |

## Commands

```bash
# Enter with USDC, then run bracket guard (live)
bds-agent guard run --profile bds-tgtest2 \
  --pool 0xE0554a476A092703abdB3Ef35c80e0D76d32939F \
  --token 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2 \
  --enter --size 5 \
  --threshold-high 2010 --threshold-low 2001 \
  --poll 5 --slippage 0.03 --dry-run

# Later runs — pool (and base_token) restored from .guard.json
bds-agent guard run --profile bds-tgtest2 \
  --threshold-high 2010 --threshold-low 2001 --poll 5

# Inspect persisted pool + position
bds-agent guard status --profile bds-tgtest2

# Verbose ticks (pool address on every line; startup always prints pool_addr + base_token)
bds-agent guard run --profile bds-tgtest2 --pool 0xE055... --token 0xC02a... \
  --threshold-high 2010 --threshold-low 2001 -v
```

Startup line (situation #4 fix — address visible, not label-only):

```text
guard pool=USDC/WETH pool_addr=0xE0554a476A092703abdB3Ef35c80e0D76d32939F base_token=0xC02a... ...
[guard] tick=1 pool=USDC/WETH 0xE0554a476A092703abdB3Ef35c80e0D76d32939F base_token=0xC02a... bds_epoch=... price=$...
```

## State file

`~/.config/bds-agent/profiles/<profile>.guard.json`:

- `pool_address`, `pool_label`, `base_token` — watched market
- `threshold_high`, `threshold_low` — last run bounds
- `position` — `token` | `reserve`
- `last_price_usd`, `last_epoch`, `bds_project`, `last_action`

## Stuck / pending transactions

`--enter` sends **approve** then **swap** (two sequential txs). If you **Ctrl+C** mid-flight, a pending tx can block the next run with `replacement transaction underpriced`.

The agent now:

- Uses **`pending`** nonce for approve → swap sequencing
- **Waits** for pending txs to clear before a new approve/swap bundle (up to 5 min)
- **Bumps fees** automatically on nonce conflicts

If it still fails, wait for pending txs in your wallet or speed them up, then retry.

## Related

- `bds-agent prices at <token> --pool <pool>` — probe the same price route
- Recipe spec: Powerloom `ai-coord-docs/recipes/THRESHOLD_GUARD.md`
