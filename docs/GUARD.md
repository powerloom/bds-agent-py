# Threshold Guard — `bds-agent guard`

Bracket trades on **one** USDC-quoted pool. Price source: `GET /mpp/token/price/{token}/{pool}` (BDS spot USD per base token). Uses the same profile API key and **`profiles/<name>.trade.env`** swap wallet as **`bds-agent trade`**.

## Commands

| Command | Purpose |
|---------|---------|
| `bds-agent guard run` | Poll BDS spot, edge-trigger bracket trades (default **spot** %% bands) |
| `bds-agent guard enter` | One-shot USDC → base at spot (same as `guard run --enter` without polling) |
| `bds-agent guard status` | Read `.guard.json` (position, bands, `guard_exit_reason`, …) |
| `bds-agent guard reset` | Clear exit/entry anchors + set `fresh_leg` (keeps pool + %% settings); then `guard run --enter` |

After each on-chain fill, guard mirrors **ENTRY** / **EXIT** into **`trader.json`** and the trades log for the same profile — use **`bds-agent trade status`**, **`history`**, **`pnl`** alongside **`guard status`**.

## Spot mode (default)

No finance jargon required: you buy at **whatever the feed says now**, sell after a **percent gain**, and only buy back after the market **gives back part of that gain**.

| Flag | Default | Role |
|------|---------|------|
| **`--enter`** | on | Swap **`--size`** USDC → base at current BDS spot (`--no-enter` if you already hold) |
| **`--take-profit-pct`** | `0.03` | Exit when price rises **+3%** above the entry spot (e.g. `0.05` = +5%) |
| **`--stop-loss-pct`** | *(off)* | Optional: exit when price falls **−X%** below entry (e.g. `0.02` = −2%) |
| **`--reentry-retrace-pct`** | `0.5` | After exit, re-enter on cross **down**: after a **win**, give back half the gain; after a **stop**, dip half the loss **below** the exit (cheaper buy) |
| **`--reserve-max-minutes`** | `0` | In USDC after an exit, stop guard if no dip re-entry within **N** minutes (`0` = poll forever). Sets `guard_exit_reason=reserve_idle_timeout` in `.guard.json` for orchestrators |

**Take-profit example:** entry **$2000**, +3% → sell near **$2060**. Retrace **0.5** → re-buy on cross down through **$2030** (half the $60 gain given back).

**Stop-loss example:** entry **$2000**, `--stop-loss-pct 0.02` → sell near **$1960**. Retrace **0.5** → re-buy on cross down through **$1940** (another $20 below the stop — not a bounce toward $2000).

```bash
bds-agent trade setup-evm --profile bds-tgtest2
bds-agent guard run --profile bds-tgtest2 \
  --pool 0xE0554a476A092703abdB3Ef35c80e0D76d32939F \
  --token 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2 \
  --size 5 --take-profit-pct 0.003 --stop-loss-pct 0.002 \
  --reentry-retrace-pct 0.5 --reserve-max-minutes 30 --poll 5
```

(`--enter` is on by default; add `--no-enter` if you already hold base.)

One-shot entry at spot:

```bash
bds-agent guard enter --profile bds-tgtest2 \
  --pool 0xE0554a476A092703abdB3Ef35c80e0D76d32939F \
  --token 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2 \
  --size 5
```

**Edge-triggered:** actions fire on **crosses** between polls (`prev → current`), not every tick while price sits inside a band.

## Explicit mode (compose)

Pass **both** USD thresholds when you want fixed levels instead of %% from entry:

```bash
bds-agent guard run --profile bds-tgtest2 \
  --pool 0xE0554a476A092703abdB3Ef35c80e0D76d32939F \
  --token 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2 \
  --threshold-high 2010 --threshold-low 2001 \
  --no-enter --poll 5
```

| Position | Cross | Action |
|----------|-------|--------|
| **token** | up through `--threshold-high` | take-profit sell |
| **token** | down through `--threshold-low` | stop-loss sell |
| **reserve** | down through `--threshold-low` | dip re-entry |
| **reserve** | up through `--threshold-high` | breakout re-entry (only with `--reentry-on-breakout`) |

## Pool + token

| Flag | Required | Role |
|------|----------|------|
| `--pool` | First run | Uniswap V3 pool; persisted to `.guard.json` |
| `--token` | Optional | Base token for the price route |

## State file

`~/.config/bds-agent/profiles/<profile>.guard.json`:

- `pricing_mode` — `spot` | `explicit`
- `position` — `token` (long base) | `reserve` (USDC after exit)
- `reference_entry_usd`, `last_exit_usd` — spot anchors for %% bands
- `reserve_since`, `reserve_max_minutes` — idle timer after exit (orchestration)
- `guard_exit_reason` — e.g. `reserve_idle_timeout` when `--reserve-max-minutes` fired
- `take_profit_pct`, `stop_loss_pct`, `reentry_retrace_pct` — last run settings
- `pool_address`, `base_token`, `last_price_usd`, `last_action`, `pending_action`

Guard does **not** call `last_finalized_epoch` or pass ProtocolState addresses — the resolver serves spot prices. On-chain verification uses **`bds-agent run`** + **`verify: true`** only (`bds-agent config init` alpha defaults).

Each executed guard fill (entry / take-profit / stop / re-entry) is mirrored into the **same profile’s** `trader.json` and trades log, so `bds-agent trade status`, `history`, and `pnl` stay in sync. Use `bds-agent guard status` for bracket-specific fields (`.guard.json`).

### Composed / orchestrated runs

One guard cycle: **enter → bracket → exit to USDC → optional dip re-entry**.

If price only rips higher after take-profit, dip re-entry never fires and the process would poll forever. Set **`--reserve-max-minutes N`** so guard stops in USDC and sets **`guard_exit_reason=reserve_idle_timeout`**. Your outer agent can then start another leg (new `guard run`, `trade run`, different pool, etc.).

```bash
# Parent loop (pseudo): run guard until idle exit or keyboard interrupt
bds-agent guard run --profile myagent ... --reserve-max-minutes 45
reason=$(jq -r .guard_exit_reason ~/.config/bds-agent/profiles/myagent.guard.json)
# reason == reserve_idle_timeout → cycle complete; else crashed or Ctrl+C

# Next leg: same command with --enter (clears stale reserve timer + idle reason)
bds-agent guard run --profile myagent ... --reserve-max-minutes 45 --enter
# Or: bds-agent guard reset --profile myagent && guard run ... --enter
```

After **`reserve_idle_timeout`**, a new `guard run --enter` starts a **fresh leg** (USDC → base at spot). Without `--enter`, the run only watches for dip re-entry and gets a **new** reserve idle window (stale `reserve_since` is not reused).

| `guard_exit_reason` | Meaning |
|---------------------|---------|
| `reserve_idle_timeout` | No dip re-entry within `--reserve-max-minutes` |
| *(unset)* | Still running, re-entered, or stopped manually |

**Pulse vs guard:** [`TRADE.md`](TRADE.md) — stream confluence, multi-pool. Guard — one pool, %% brackets, poll-based. Same wallet files; different state files.

## Logs

Stdout uses the same **UTC timestamp + Rich colors** as `bds-agent trade` pulse mode (`[bold blue]GUARD[/]` ticks, green/red actions). Disable with `NO_COLOR=1`.

## STF / slippage / pending txs

**BDS price poll:** `GET /mpp/token/price/...` retries up to **5** times on **502 / 503 / 504 / 429** and network errors (exponential backoff, honors `Retry-After`). Guard logs `[yellow]PRICE RETRY[/]` lines; then `price=unavailable` only if all attempts fail.

**HTTP 402** on price poll raises with top-up hint (`https://bds-metering.powerloom.io/metering` or `bds-agent credits topup`).

Pool fee from chain before live entry; STF / slippage retry; `pending_action` backoff; pending mempool wait before `--enter`.

## Related

- `bds-agent prices at <token> --pool <pool>` — probe the same price route
