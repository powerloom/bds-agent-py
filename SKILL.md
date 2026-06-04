---
name: bds-agent
description: |
  Python CLI for Powerloom BDS: metering (signup, pay-signup, credits), agent.yaml runners,
  NL query/create with LLM, local MCP to BDS, Pulse trader (Uniswap V3), Threshold Guard
  bracket trading (USDC entry, take-profit/stop-loss on BDS USD prices).
  Use for "bds-agent", "Powerloom API key", "credits", "MCP bds", "agent.yaml", "Uniswap",
  "bds-agent trade", "Pulse trader", "bds-agent guard", "threshold guard", "guard rail".
version: 0.1.1
homepage: https://github.com/powerloom/bds-agent-py
repository: https://github.com/powerloom/bds-agent-py
tags:
  - python
  - powerloom
  - bds
  - mcp
  - agents
  - uniswap
metadata:
  language: python
  package: bds-agent
  install:
    - "cd bds-agent-py && uv tool install ."
    - "When published: uv tool install bds-agent"
  primary_docs: https://github.com/powerloom/bds-agent-py/blob/main/docs/USER_GUIDE.md
  metering_default: https://bds-metering.powerloom.io
  bds_api_example: https://bds.powerloom.io/api
  mcp_hosted: https://bds-mcp.powerloom.io/sse
---

# bds-agent (Powerloom BDS CLI)

> **Version:** 2026-06-01 · **Canonical human docs:** [docs/USER_GUIDE.md](https://github.com/powerloom/bds-agent-py/blob/main/docs/USER_GUIDE.md) (install, profiles, metering HTTP, MCP, LLM, **trade**, **guard**). Re-read that file after `git pull` or `uv tool install --force .`.

This file is a **framework-neutral** index: any orchestrator, IDE, or autonomous agent can read it to learn how to drive the **bds-agent** CLI and the **public HTTP** surfaces it calls. It is not a substitute for `USER_GUIDE.md` (full tables, precedence, troubleshooting).

## What it is

- **bds-agent** is a Python **Typer** CLI + **httpx** client. It stores API keys under **`~/.config/bds-agent/profiles/<name>.json`** and optional **`active_profile`**.
- **Per-profile wallet files** (same `<name>` as the profile JSON — pick any label, e.g. `pulse`; do **not** use a profile name that reads like a subcommand):
  - **`profiles/<name>.evm.env`** — **billing** (`EVM_*`): `signup-pay`, on-chain credit top-up
  - **`profiles/<name>.trade.env`** — **swaps** (`TRADE_EVM_*`): `bds-agent trade run` only
  - **`profiles/<name>.tempo.env`** — Tempo `credits topup` when your deploy uses Tempo
  - **`profiles/<name>.trader.json`**, **`profiles/<name>.trades.jsonl`** — Pulse trader state + log
  - **`profiles/<name>.guard.json`** — Threshold Guard position + pool + thresholds
- **Metering** (signup, API keys, credits) talks to a single **origin** (default **`https://bds-metering.powerloom.io`**) — same host as the browser flow at **`/metering`**. Set **`BDS_AGENT_SIGNUP_URL`** to override.
- **BDS data** (Uniswap and other markets) is a **separate** HTTP origin: **`BDS_BASE_URL`**, e.g. **`https://bds.powerloom.io/api`**. `bds-agent run`, **`query`**, and **`mcp`** need an API key + this base URL (often via **`bds-agent config init`** on the profile).

## Session bootstrap (copy-paste)

```bash
# Optional: read this skill from the repo
curl -sL https://raw.githubusercontent.com/powerloom/bds-agent-py/main/SKILL.md

# Install (pick one)
cd bds-agent-py && uv tool install .
# or from PyPI when published: uv tool install bds-agent

bds-agent --help
bds-agent --version
```

After install changes, use **`uv cache clean`**, **`uv tool install --force .`**.

## Metering: HTTP first (no CLI required)

The metering service implements **bds-agenthub-billing-metering**. Authoritative order:

| Step | API | Auth |
|------|-----|------|
| List SKUs | `GET {BASE}/credits/plans` | None |
| Pay-signup (headless) | `POST {BASE}/signup/pay/quote` → pay on chain → `POST {BASE}/signup/pay/claim` | None until you have `api_key` |
| Device signup | `POST {BASE}/signup/initiate` + browser + `GET {BASE}/signup/status` | Session |
| Balance | `GET {BASE}/credits/balance` | `Authorization: Bearer sk_live_…` |
| Usage ledger | `GET {BASE}/credits/usage?limit=100` | Bearer |
| Usage summary | `GET {BASE}/credits/usage/summary?days=7` | Bearer |
| Usage by endpoint | `GET {BASE}/credits/usage/by-endpoint?days=30&limit=50` | Bearer |
| More credits (existing key) | `POST {BASE}/credits/topup` | Bearer + `plan_id`, `chain_id`, `tx_hash` |

`{BASE}` = **`BDS_AGENT_SIGNUP_URL`** (default `https://bds-metering.powerloom.io`). **Full** field lists and `bds-agent` wrappers: [USER_GUIDE — Metering service API](https://github.com/powerloom/bds-agent-py/blob/main/docs/USER_GUIDE.md#metering-service-api-authoritative-order) and [End-to-end path](https://github.com/powerloom/bds-agent-py/blob/main/docs/USER_GUIDE.md#end-to-end-path).

**Agent-first (recommended for automation):** `credits plans` → `credits setup-evm` → `signup-pay` (no API key before payment). **Browser path:** `signup` then `credits balance`.

## Command surface (CLI)

| Command | Purpose |
|---------|---------|
| `bds-agent signup` | Device-auth; browser verify; saves API key to profile |
| `bds-agent signup-pay` | Wallet-funded API key (`--plan-id`, `--chain-id`, `--token-symbol`); see **USER_GUIDE** |
| `bds-agent credits plans` | Pretty-print `GET /credits/plans` (no key) |
| `bds-agent credits setup-evm` | Save **billing** EVM key to `profiles/<n>.evm.env` (pay-signup / EVM top-up) |
| `bds-agent credits setup-tempo` | Save Tempo key for **Tempo**-style `credits topup` when your deploy uses that path |
| `bds-agent credits balance` | Balance + rate limits (Bearer) |
| `bds-agent credits usage` | Recent ledger rows with route/method/path/source |
| `bds-agent credits usage summary` | Daily totals + endpoint rollup (`--days`) |
| `bds-agent credits usage by-endpoint` | Endpoint-only rollup (`--days`, `--limit`) |
| `bds-agent credits topup` | On-chain top-up (after `setup-tempo` or as implemented for your plan); or dev ` --amount` + ` --dev-secret` |
| `bds-agent trade setup-evm` | Save **swap** wallet to `profiles/<n>.trade.env` (`TRADE_EVM_*`; separate from billing) |
| `bds-agent trade run` | Pulse trader: BDS SSE → confluence → Uniswap V3 multi-pool (USD price gate); see **TRADE.md** |
| `bds-agent trade status` / `history` / `pnl` / `exit` | Trader position, log, P/L summary, manual close |
| `bds-agent prices at` / `prices token` | Pool-scoped or all-pools USD spot (`/mpp/token/price/`, `/mpp/tokenPrices/all/`) |
| `bds-agent guard run` | Threshold Guard: spot %% TP/SL + dip re-entry on one pool; see **GUARD.md** |
| `bds-agent guard enter` | One-shot USDC → base at BDS spot (no polling) |
| `bds-agent guard status` | `.guard.json`: position, bands, `guard_exit_reason` |
| `bds-agent guard reset` | Clear cycle anchors after `reserve_idle_timeout`; then `guard run --enter` |
| `bds-agent run <agent.yaml>` | Stream/fetch BDS, rules, sinks; optional **`verify: true`** in YAML |
| `bds-agent query "…"` | NL → catalog route + params; optional **`--execute`** to call BDS |
| `bds-agent create "…"` | NL → `agent.yaml` (needs LLM) |
| `bds-agent mcp` | **stdio** MCP server: one tool per **filtered** catalog route (default paths **`/mpp`**) |
| `bds-agent llm status` / `llm use` / `llm setup` / `llm ping` | LLM backends for **query** / **create** |
| `bds-agent config init` / `show` / `set` / `unset` | Profile **JSON**: `bds_base_url`, catalog URLs, Powerloom `verify` defaults |

Deeper help: `bds-agent <cmd> --help` and the [README](https://github.com/powerloom/bds-agent-py/blob/main/README.md) command table.

## Pulse trader (`bds-agent trade`)

Streams **`/mpp/stream/allTrades`**, runs Pulse entry/exit rules, swaps on Uniswap V3 (ETH mainnet). **`--multi-pool`** watches top USDC pools; **`--price-source usd`** (default) uses premium **`/mpp/tokenPrices/`**. Full flags: [docs/TRADE.md](https://github.com/powerloom/bds-agent-py/blob/main/docs/TRADE.md).

**Bootstrap (example profile `pulse` — any name works; same `--profile` everywhere):**

```bash
bds-agent signup --profile pulse                    # API key → profiles/pulse.json
bds-agent credits setup-evm --profile pulse         # optional: billing wallet → pulse.evm.env
bds-agent trade setup-evm --profile pulse           # swap wallet → pulse.trade.env

# Phase 1: dry run (no on-chain swaps) — multi-pool + USD recommended
bds-agent trade run --profile pulse --dry-run --multi-pool --verbose

# Phase 2: live
bds-agent trade run --profile pulse --multi-pool --price-source usd --size 25 --max-open-positions 5 --daily-loss-limit 50
```

**Defaults:** `--price-source usd`, `--price-move 0.15`, `--volume-burst 2.0`, `--flow-imbalance 30`, `--exit-take-profit-pct 1.0`, `--active-pool-limit 40`, `--max-open-positions 0` (auto: 5 with `--multi-pool`), `--reentry-cooldown-minutes 0`, `--signal-cooldown-minutes 0`, `--daily-loss-limit 50`. All exit modes on by default — disable with `--no-exit-*`.

**Billing:** Stream + premium **`/mpp/tokenPrices/`** API credits when using USD price source — **not** a separate agent-action fee. Check **`bds-agent credits usage by-endpoint`**.

**Critical:** `trade run` reads **`TRADE_EVM_*`** from **`.trade.env` only** — never billing **`EVM_*`** from **`.evm.env`**. Live startup strips paper positions/cooldowns. **`--price-source`** must be `usd` or `trades` (validated). Ops: **`status`**, **`history`**, **`pnl`**, **`exit`**, **`reconcile`**.

## Threshold Guard (`bds-agent guard`)

**Bracket guard-rail** on one USDC-quoted pool: poll **`GET /mpp/token/price/{token}/{pool}`**, edge-triggered sells (TP/SL) and dip re-entry. Complements **Pulse** (`trade run`) — one pool, %% bands, not stream confluence.

**Bootstrap (same profile + `trade.env` as Pulse):**

```bash
bds-agent signup --profile myguard
bds-agent trade setup-evm --profile myguard

# Spot mode (default): %% from entry; --enter on by default
bds-agent guard run --profile myguard \
  --pool 0xE0554a476A092703abdB3Ef35c80e0D76d32939F \
  --token 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2 \
  --size 5 --take-profit-pct 0.003 --stop-loss-pct 0.002 \
  --reentry-retrace-pct 0.5 --reserve-max-minutes 30 --poll 5

bds-agent guard status --profile myguard   # .guard.json
bds-agent trade status --profile myguard   # mirrored LONG/FLAT + P/L
```

**Spot flags (defaults):** `--take-profit-pct 0.03`, `--reentry-retrace-pct 0.5`, optional `--stop-loss-pct`, **`--reserve-max-minutes`** (exit process in USDC if no dip re-entry — sets `guard_exit_reason=reserve_idle_timeout` for orchestrators). **`--enter`** / **`--no-enter`**, `--size`, `--poll`, `--slippage`, `--pool`, `--token`, `--dry-run`, `-v`.

**Explicit mode:** both `--threshold-high` and `--threshold-low` (USD per 1 base token); optional `--reentry-on-breakout` (explicit only today).

**Behavior:** Edge-triggered crosses between polls. After TP/SL → **`reserve`** (USDC); dip re-entry on cross down through `reentry_below`. **`--reserve-max-minutes`** sets `guard_exit_reason=reserve_idle_timeout` — orchestrators call **`guard reset`** then **`guard run … --enter`** for the next leg.

**Trade sync:** Each guard fill appends to **`profiles/<n>.trades.jsonl`** and updates **`trader.json`** — same profile as **`trade status`** / **`pnl`**.

**Logs:** UTC timestamp + Rich colors (`GUARD` / `EXEC` / `DONE` lines). `NO_COLOR=1` disables color.

**Approve + swap** are sequential txs; pending mempool is waited on before `--enter`. Full reference: [docs/GUARD.md](https://github.com/powerloom/bds-agent-py/blob/main/docs/GUARD.md).

## Environment and profiles (short)

- **`BDS_AGENT_PROFILE`**, **`--profile`**: which `profiles/<name>.json` to use.
- **`BDS_BASE_URL`**: snapshotter API origin (different from metering).
- **`BDS_API_ENDPOINTS_CATALOG_JSON`** or **`BDS_SOURCES_JSON`**: [endpoint catalog](https://github.com/powerloom/bds-agent-py/blob/main/docs/USER_GUIDE.md#api-endpoint-catalog-endpointsjson) for **run** / **query** / **mcp** / **create**.
- **`BDS_AGENT_CATALOG_PATH_PREFIXES`**: default filter **`/mpp`** for catalog tools.

Full list: [USER_GUIDE — Prerequisites and env](https://github.com/powerloom/bds-agent-py/blob/main/docs/USER_GUIDE.md).

## Responses: verification, not a separate `verify` CLI

BDS and MCP tool payloads can include **`verification`** (e.g. **CID**, **epochId**, **projectId**). The **`bds_mpp_*` / `verify_data_provenance` tools** and **`agent.yaml`** with **`verify: true`** are how you check on-chain commitments — there is no standalone `bds-agent verify` command. See [AGENT_YAML.md](https://github.com/powerloom/bds-agent-py/blob/main/docs/AGENT_YAML.md) and [USER_GUIDE — On-chain snapshot verification](https://github.com/powerloom/bds-agent-py/blob/main/docs/USER_GUIDE.md#on-chain-snapshot-verification-bds-agent-run).

## Failure modes (orchestrators)

| Condition | Behavior |
|-----------|----------|
| **HTTP 402** / zero credits on USD price routes | **`RuntimeError`** with hint: add credits at **`https://bds-metering.powerloom.io/metering`** or **`bds-agent credits topup`** — not silent hold |
| **Invalid / expired API key** on SSE stream | **`BdsClientError`** — process exits; no infinite reconnect |
| **Transient BDS 502/503/504/429** (guard price poll) | Retries with `[PRICE RETRY]` logs; then `price=unavailable` |
| **Swap failure** (trade/guard) | Logged; guard keeps `pending_action` + backoff; trade single-pool **`continue`**s epoch loop |
| **`reserve_idle_timeout`** | Guard exits; read **`guard_exit_reason`** from **`.guard.json`**; **`guard reset`** + **`guard run --enter`** for fresh leg |

Metering **origin** (`BDS_AGENT_SIGNUP_URL`, default **`https://bds-metering.powerloom.io`**) is **not** the browser UI path — human top-up is **`/metering`** on the same host.

## Common mistakes

- **Mixing URLs:** Metering origin **≠** **`/metering`** UI **≠** BDS `BDS_BASE_URL`. Store all three correctly (`config init` helps for BDS).
- **MCP and stdout:** **Nothing** may print to stdout except JSON-RPC from **`bds-agent mcp`**.
- **Catalog empty:** Set **`BDS_API_ENDPOINTS_CATALOG_JSON`** or **`BDS_SOURCES_JSON`** and **`BDS_BASE_URL`**, plus a valid API key on the profile.
- **Pay-signup / top-up:** `plan_id`, `chain_id`, and `token_symbol` must match a **`GET /credits/plans`** row; on-chain `from` must match the quoted payer for pay-signup.
- **Trade vs billing wallet:** Do not fund or swap from **`profiles/<n>.evm.env`** for **`trade run`**. Run **`trade setup-evm`** for **`profiles/<n>.trade.env`**. Same profile JSON/API key for both.
- **Profile name in examples:** Use neutral labels like **`pulse`** or **`myagent`** — avoid names that mirror subcommands (e.g. a profile literally named `trading` next to `trade setup-evm` confuses operators).
- **weaker models + query:** The catalog is large; use path filters; see **USER_GUIDE** (LLM, **OLLAMA_NUM_CTX**).

## Hosted MCP (no local `bds-agent` process)

To call tools over SSE, use a remote MCP client against **`https://bds-mcp.powerloom.io/sse`** (or your deploy) with **`Authorization: Bearer <sk_live_…>`** as required by that server. The **bds-agent** repo’s `mcp` subcommand is **stdio** for local IDEs. See [USER_GUIDE — Local MCP server](https://github.com/powerloom/bds-agent-py/blob/main/docs/USER_GUIDE.md#local-mcp-server-bds-agent-mcp).

## Resources (canonical)

| Resource | URL |
|----------|-----|
| **User guide (full)** | [docs/USER_GUIDE.md on GitHub](https://github.com/powerloom/bds-agent-py/blob/main/docs/USER_GUIDE.md) |
| **Pulse trader (`trade`)** | [docs/TRADE.md](https://github.com/powerloom/bds-agent-py/blob/main/docs/TRADE.md) |
| **Threshold Guard (`guard`)** | [docs/GUARD.md](https://github.com/powerloom/bds-agent-py/blob/main/docs/GUARD.md) |
| **USD prices (`prices`)** | [docs/PRICES.md](https://github.com/powerloom/bds-agent-py/blob/main/docs/PRICES.md) |
| **agent.yaml** | [docs/AGENT_YAML.md](https://github.com/powerloom/bds-agent-py/blob/main/docs/AGENT_YAML.md) |
| **Metering / billing service** | [bds-agenthub-billing-metering README](https://github.com/powerloom/bds-agenthub-billing-metering#readme) |
| **ClawHub Uniswap V3 skill (Node + recipes)** | [powerloom-bds-univ3](https://github.com/powerloom/powerloom-bds-univ3) (optional; different repo) |

A future static **`https://<metering>/skill.md`** can mirror this file with a **`Version: YYYY-MM-DD | Re-fetch: curl …`** line so session boots always pull fresh copy; until then, this **`SKILL.md`** in the repo is the **source of truth** for content.
