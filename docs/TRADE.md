# bds-agent trade — Pulse self-contained trader

**CLI**: `bds-agent trade setup-evm|run|status|history|pnl|exit`

Streams BDS Uniswap V3 epochs, detects **Pulse** confluence (price + volume + flow), swaps on ETH mainnet via Uniswap V3 SwapRouter. One position at a time.

**Premium data:** Production Pulse uses the **USD Price Feed** (`--price-source usd`, default) for block-accurate price moves. Billing is **stream + `/mpp/tokenPrices/`** API credits — not a separate CLI action fee. See **Metering** below.

---

## Profile layout (one API key, three wallets)

For profile `pulse`:

| File | Purpose |
|------|---------|
| `profiles/pulse.json` | BDS API key (`sk_live_…`) — stream, billing, all commands |
| `profiles/pulse.evm.env` | **Billing** — `signup-pay`, on-chain credit top-up |
| `profiles/pulse.trade.env` | **Trading** — Uniswap swaps only |
| `profiles/pulse.tempo.env` | Tempo credit top-up (if used) |
| `profiles/pulse.trader.json` | Open position state |
| `profiles/pulse.trades.jsonl` | Trade log |

Same `--profile pulse` everywhere; **never** use the billing wallet for swaps.

---

## Quick start

```bash
bds-agent signup --profile pulse              # API key → pulse.json
bds-agent credits setup-evm --profile pulse   # billing wallet (optional)
bds-agent trade setup-evm --profile pulse     # swap wallet → pulse.trade.env

# Phase 1: dry run — multi-pool + USD price gate (recommended)
bds-agent trade run --profile pulse --dry-run --multi-pool --verbose

# Phase 2: live (same flags, drop --dry-run)
bds-agent trade run --profile pulse --multi-pool --price-source usd --size 25
```

Fund the **trading** wallet with USDC (swap size) + ETH (gas). First swap per token may require a separate **ERC-20 approve** tx before the router swap.

---

## Entry defaults

| Flag | Default | Meaning |
|------|---------|---------|
| `--price-source` | `usd` | Price gate: `usd` = `/mpp/tokenPrices/`; `trades` = trade-implied only |
| `--price-move` | 0.15 | Min price change % in 5 min window |
| `--volume-burst` | 2.0 | Short-window volume vs trailing baseline |
| `--flow-imbalance` | 30 | Directional flow as % of volume |
| `--window-minutes` | 5 | Signal lookback |
| `--reentry-cooldown-minutes` | 0 | Optional: block **all** new entries for N minutes after a **live** exit |
| `--signal-cooldown-minutes` | 0 | Optional: per pool, suppress repeat LONG signals for N minutes after a fire |
| `--max-open-positions` | auto | Max concurrent LONGs (one per pool). **0** = 5 with `--multi-pool`, else 1 |
| `--daily-loss-limit` | 50 | No new entries if today P/L ≤ -$50 (UTC) |

Only **one LONG per pool**; up to **`--max-open-positions`** concurrent pools (default **5** with `--multi-pool`, **1** otherwise). **Dry-run** exits set cooldown in paper state only; starting **live** without `--dry-run` clears paper positions and paper cooldown (`prepare_live_trader_state`).

---

## Multi-pool mode (`--multi-pool`)

Watches **USDC-quoted pools** from `GET /mpp/dailyActivePools` (default: top **40**, `time_interval=300` = 5m). Each epoch:

1. Ingest trades per pool from the same `allTrades` stream  
2. Run Pulse on each buffer (USD price gate when `--price-source usd`)  
3. Pick the **strongest LONG** candidates not already held (up to open-slot limit)  
4. **Live:** USDC ↔ token swap on each selected pool via Uniswap V3 SwapRouter (not WETH-only)

```bash
bds-agent trade run --profile pulse --dry-run --multi-pool --verbose \
  --active-pool-limit 40 --active-interval 300 --price-source usd --max-open-positions 5
```

Watchlist refreshes every 30 epochs (~6 min on mainnet).

**Why USD matters:** On deep pairs like WETH/USDC, trade-implied `px=` can sit at **0%** while quieter alt pools (e.g. AI/USDC) show real moves — multi-pool + USD feed is the production path.

---

## Price source (`--price-source`)

| Value | Price gate | Typical use |
|-------|------------|-------------|
| **`usd`** (default) | `GET /mpp/tokenPrices/all/{token}/{block}` | Production Pulse; premium metered |
| **`trades`** | Last swap prices from stream buffer | Legacy / debugging |

Volume burst and flow imbalance always use trade tape from the stream.

---

## Verbose heartbeat

Per-epoch heartbeat (ported from the reference `pulse.mjs` script):

```text
2026-05-27T14:32:01Z HB pool=USDC/WETH epoch=12345 spot=3042.50 px=+0.31% burst=2.10x imb=42% n=8 added=3 buf=120 pos=FLAT ready gates price=PASS burst=PASS imb=fail
2026-05-27T14:32:01Z   → gates not met: imb
```

Every `trade run` stdout line is prefixed with **UTC** time (`YYYY-MM-DDTHH:MM:SSZ`). Redirect to a file for overnight post-mortems.

While **LONG**, the exit rule tree prints **only on the entry pool** (multi-pool). Other pools may show signals but not bogus cross-pool P/L:

```text
  → exit ·stop_loss(+0.12% / -2.0%) ·take_profit(+0.28% / +1.0%) ·trailing_stop(-0.05% from peak / -2.0%) ·time_based(3.2m / 10m) ·signal_reversal(—)
```

**Take-profit display:** `take_profit(+0.28% / +1.0%)` means **current unrealized move / threshold** — not profit already banked.

**SHORT** while flat: `→ signal SHORT ignored (LONG-only entry)`. **SHORT** on another pool while long: `→ signal SHORT ignored (not entry pool)`. **SHORT** on the entry pool while long can trigger `signal_reversal`.

On **LONG** signal while flat, shows entry decision (`entry OK` or `entry BLOCKED: spot move down|reentry_cooldown|daily_loss_limit|position_open`).

**Exit sells** the full on-chain base-token balance for that pool (dust sweep), capped by `_cap_sell_amount_atomic` at the router.

**LONG entry** (default `--block-long-on-down-move`): skips new LONG when 5m `px` is negative (`--price-source usd` uses BDS USD window; `trades` uses swap-implied window). Disable with `--no-block-long-on-down-move`.

Use during dry-run validation; stdout is one line per BDS epoch (~12s on ETH mainnet). With `--verbose`, Rich colors apply when stdout is a TTY (or set `FORCE_COLOR=1`; respect `NO_COLOR`).

| Element | Color |
|---------|--------|
| `HB` / startup | blue header |
| `pool=` | cyan; **magenta** when entry pool |
| `px=` | green if gate pass; yellow/red by direction |
| `burst` / `imb` values | green or red by gate |
| `PASS` / `fail` | green / red |
| `LONG` / `FLAT` | bold green / dim |
| `→ signal LONG` | bold green |
| `→ signal SHORT` | bold red (or dim if ignored) |
| Exit `!rule` | bold red when triggered |

---

## Exit strategies (all optional flags)

All exit modes are **on by default**. Disable any with `--no-exit-*`. The first rule that matches closes the position.

| Flag | Default | What it does |
|------|---------|--------------|
| `--exit-stop-loss` | on | Cut loss if price falls X% below entry |
| `--exit-stop-loss-pct` | 2.0 | Stop distance (%) |
| `--exit-take-profit` | on | Take gain if price rises X% above entry |
| `--exit-take-profit-pct` | 1.0 | Target gain (%) |
| `--exit-trailing-stop` | on | Exit if price falls X% from **best price since entry** |
| `--exit-trailing-pct` | 2.0 | Trail distance (%) |
| `--exit-time-based` | on | Exit after N minutes regardless of price |
| `--exit-hold-minutes` | 10 | Max hold time |
| `--exit-signal-reversal` | on | Exit when Pulse fires SHORT |

Check order: **stop-loss → take-profit → trailing-stop → time-based → signal-reversal**.

---

## Stop-loss (plain English)

You bought a token because you expect the price to go **up**. Sometimes it goes **down** instead.

A **stop-loss** is a pre-set rule: *“If I’m down X% on this trade, sell and accept the small loss — don’t wait for a bigger one.”*

Example with defaults (`--exit-stop-loss-pct 2`):

- Entry: token ≈ **$3,000** (or any spot from USD feed)
- Stop triggers near **2% below entry**
- On a **$25** position, that’s roughly **-$0.50** before fees/gas

It does **not** guarantee exactly $0.50 — slippage and gas matter — but it caps how long you ride a losing move.

**Take-profit** is the mirror: sell when you’re **up** X%.  
**Trailing stop** watches the **highest** price after entry and sells if price falls X% from that peak.

---

## Risk controls

| Control | Behavior |
|---------|----------|
| Max positions | Up to `--max-open-positions` (one LONG per pool; default 5 with `--multi-pool`) |
| Re-entry cooldown | Off by default. Per-pool when `--max-open-positions` > 1; global when max is 1 |
| Signal cooldown | Off by default (`--signal-cooldown-minutes 0`). When set, per-pool LONG fire spacing in Pulse |
| Daily loss limit | Realized exits today (UTC) summed; block entries if ≤ -$50 |
| Dry-run vs live | Paper LONG does not block live startup; paper cooldown cleared on live start |
| Manual exit | `bds-agent trade exit --profile pulse` (all) or `--pool 0x…` (one) |
| Wallet isolation | Trading uses `.trade.env` only; billing uses `.evm.env` |

Gas is **not** included in logged P/L (tx hash recorded for your own accounting).

---

## Metering

| Route | When | Notes |
|-------|------|-------|
| `/mpp/stream/allTrades` | Every `trade run` session | Debited **per SSE connection** (see USER_GUIDE) |
| `/mpp/tokenPrices/...` | Each epoch per watched token when `--price-source usd` | Premium; scales with pool count |
| `/mpp/dailyActivePools` | Watchlist refresh (~every 30 epochs) | Standard GET |

```bash
bds-agent credits balance
bds-agent credits usage by-endpoint --days 7 --limit 50
```

There is **no** separate charge for “Pulse actions” or running `bds-agent trade`.

**HTTP 402:** USD price fetches raise with a top-up hint (`https://bds-metering.powerloom.io/metering` or `bds-agent credits topup`) — the trader stops rather than running on stale prices.

**Invalid API key:** SSE stream fails with `BdsClientError` (no infinite reconnect).

---

## Ops commands

```bash
bds-agent trade setup-evm --profile pulse
bds-agent trade status --profile pulse    # shows LONG (dry-run — not on-chain) when applicable
bds-agent trade history --profile pulse
bds-agent trade pnl --profile pulse
bds-agent trade exit --profile pulse
bds-agent trade exit --profile pulse --dry-run
```

Fund the **trading** wallet with test USDC + ETH for gas on mainnet. Keep billing USDC on `.evm.env` separate.
