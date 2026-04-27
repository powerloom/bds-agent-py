---
name: bds-agent
description: |
  Python CLI for Powerloom BDS: metering (signup, pay-signup, credits), agent.yaml runners,
  NL query/create with LLM, local MCP to BDS. Use for "bds-agent", "Powerloom API key",
  "credits", "MCP bds", "agent.yaml", "Uniswap" data agents.
version: 0.1.0
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

> **Version:** 2026-04-27 · **Canonical human docs:** [docs/USER_GUIDE.md](https://github.com/powerloom/bds-agent-py/blob/main/docs/USER_GUIDE.md) (install, profiles, metering HTTP, MCP, LLM). Re-read that file after `git pull` or `uv tool install --force .`.

This file is a **framework-neutral** index: any orchestrator, IDE, or autonomous agent can read it to learn how to drive the **bds-agent** CLI and the **public HTTP** surfaces it calls. It is not a substitute for `USER_GUIDE.md` (full tables, precedence, troubleshooting).

## What it is

- **bds-agent** is a Python **Typer** CLI + **httpx** client. It stores API keys under **`~/.config/bds-agent/profiles/<name>.json`** and optional **`active_profile`**.
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
| More credits (existing key) | `POST {BASE}/credits/topup` | Bearer + `plan_id`, `chain_id`, `tx_hash` |

`{BASE}` = **`BDS_AGENT_SIGNUP_URL`** (default `https://bds-metering.powerloom.io`). **Full** field lists and `bds-agent` wrappers: [USER_GUIDE — Metering service API](https://github.com/powerloom/bds-agent-py/blob/main/docs/USER_GUIDE.md#metering-service-api-authoritative-order) and [End-to-end path](https://github.com/powerloom/bds-agent-py/blob/main/docs/USER_GUIDE.md#end-to-end-path).

**Agent-first (recommended for automation):** `credits plans` → `credits setup-evm` → `signup-pay` (no API key before payment). **Browser path:** `signup` then `credits balance`.

## Command surface (CLI)

| Command | Purpose |
|---------|---------|
| `bds-agent signup` | Device-auth; browser verify; saves API key to profile |
| `bds-agent signup-pay` | Wallet-funded API key (`--plan-id`, `--chain-id`, `--token-symbol`); see **USER_GUIDE** |
| `bds-agent credits plans` | Pretty-print `GET /credits/plans` (no key) |
| `bds-agent credits setup-evm` | Save EVM key to `profiles/<n>.evm.env` (pay-signup / EVM top-up) |
| `bds-agent credits setup-tempo` | Save Tempo key for **Tempo**-style `credits topup` when your deploy uses that path |
| `bds-agent credits balance` | Balance + rate limits (Bearer) |
| `bds-agent credits topup` | On-chain top-up (after `setup-tempo` or as implemented for your plan); or dev ` --amount` + ` --dev-secret` |
| `bds-agent run <agent.yaml>` | Stream/fetch BDS, rules, sinks; optional **`verify: true`** in YAML |
| `bds-agent query "…"` | NL → catalog route + params; optional **`--execute`** to call BDS |
| `bds-agent create "…"` | NL → `agent.yaml` (needs LLM) |
| `bds-agent mcp` | **stdio** MCP server: one tool per **filtered** catalog route (default paths **`/mpp`**) |
| `bds-agent llm status` / `llm use` / `llm setup` / `llm ping` | LLM backends for **query** / **create** |
| `bds-agent config init` / `show` / `set` / `unset` | Profile **JSON**: `bds_base_url`, catalog URLs, Powerloom `verify` defaults |

Deeper help: `bds-agent <cmd> --help` and the [README](https://github.com/powerloom/bds-agent-py/blob/main/README.md) command table.

## Environment and profiles (short)

- **`BDS_AGENT_PROFILE`**, **`--profile`**: which `profiles/<name>.json` to use.
- **`BDS_BASE_URL`**: snapshotter API origin (different from metering).
- **`BDS_API_ENDPOINTS_CATALOG_JSON`** or **`BDS_SOURCES_JSON`**: [endpoint catalog](https://github.com/powerloom/bds-agent-py/blob/main/docs/USER_GUIDE.md#api-endpoint-catalog-endpointsjson) for **run** / **query** / **mcp** / **create**.
- **`BDS_AGENT_CATALOG_PATH_PREFIXES`**: default filter **`/mpp`** for catalog tools.

Full list: [USER_GUIDE — Prerequisites and env](https://github.com/powerloom/bds-agent-py/blob/main/docs/USER_GUIDE.md).

## Responses: verification, not a separate `verify` CLI

BDS and MCP tool payloads can include **`verification`** (e.g. **CID**, **epochId**, **projectId**). The **`bds_mpp_*` / `verify_data_provenance` tools** and **`agent.yaml`** with **`verify: true`** are how you check on-chain commitments — there is no standalone `bds-agent verify` command. See [AGENT_YAML.md](https://github.com/powerloom/bds-agent-py/blob/main/docs/AGENT_YAML.md) and [USER_GUIDE — On-chain snapshot verification](https://github.com/powerloom/bds-agent-py/blob/main/docs/USER_GUIDE.md#on-chain-snapshot-verification-bds-agent-run).

## Common mistakes

- **Mixing URLs:** Metering **≠** BDS `BDS_BASE_URL`. Store both correctly (`config init` helps).
- **MCP and stdout:** **Nothing** may print to stdout except JSON-RPC from **`bds-agent mcp`**.
- **Catalog empty:** Set **`BDS_API_ENDPOINTS_CATALOG_JSON`** or **`BDS_SOURCES_JSON`** and **`BDS_BASE_URL`**, plus a valid API key on the profile.
- **Pay-signup / top-up:** `plan_id`, `chain_id`, and `token_symbol` must match a **`GET /credits/plans`** row; on-chain `from` must match the quoted payer for pay-signup.
- **weaker models + query:** The catalog is large; use path filters; see **USER_GUIDE** (LLM, **OLLAMA_NUM_CTX**).

## Hosted MCP (no local `bds-agent` process)

To call tools over SSE, use a remote MCP client against **`https://bds-mcp.powerloom.io/sse`** (or your deploy) with **`Authorization: Bearer <sk_live_…>`** as required by that server. The **bds-agent** repo’s `mcp` subcommand is **stdio** for local IDEs. See [USER_GUIDE — Local MCP server](https://github.com/powerloom/bds-agent-py/blob/main/docs/USER_GUIDE.md#local-mcp-server-bds-agent-mcp).

## Resources (canonical)

| Resource | URL |
|----------|-----|
| **User guide (full)** | [docs/USER_GUIDE.md on GitHub](https://github.com/powerloom/bds-agent-py/blob/main/docs/USER_GUIDE.md) |
| **agent.yaml** | [docs/AGENT_YAML.md](https://github.com/powerloom/bds-agent-py/blob/main/docs/AGENT_YAML.md) |
| **Metering / billing service** | [bds-agenthub-billing-metering README](https://github.com/powerloom/bds-agenthub-billing-metering#readme) |
| **ClawHub Uniswap V3 skill (Node + recipes)** | [powerloom-bds-univ3](https://github.com/powerloom/powerloom-bds-univ3) (optional; different repo) |

A future static **`https://<metering>/skill.md`** can mirror this file with a **`Version: YYYY-MM-DD | Re-fetch: curl …`** line so session boots always pull fresh copy; until then, this **`SKILL.md`** in the repo is the **source of truth** for content.
