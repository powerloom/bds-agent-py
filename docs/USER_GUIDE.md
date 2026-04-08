# bds-agent user guide: signup → credits → Tempo top-up

This document lives in the **`bds-agent-py`** repository so it ships with the CLI and stays valid for anyone who clones **this** repo alone. It does **not** reference private workspace-only paths.

## Prerequisites

1. **Metering service** running and reachable (e.g. local `http://127.0.0.1:8787` or your deployed URL). It must expose **`GET /credits/plans`**, signup routes, and **`POST /credits/topup`** with Tempo/EVM verification configured (`MPP_TEMPO_RECIPIENT`, RPC, chain, seeded plans as needed). See the [bds-agenthub-billing-metering](https://github.com/powerloom/bds-agenthub-billing-metering) README.
2. **CLI env:** `BDS_AGENT_SIGNUP_URL` set to that metering base URL (or pass `--base-url` where supported).
3. **On-chain top-up:** a wallet funded on the **same** chain and token as the plan (e.g. pathUSD on Moderato `42431` for the default seed plan).

## End-to-end path

### 1. Sign up (device flow)

```bash
export BDS_AGENT_SIGNUP_URL=https://your-metering.example.com   # or http://127.0.0.1:8787
poetry run bds-agent signup
```

- Enter **email** and **agent name** when prompted.
- Open the **verification URL** in a browser, enter the **user code**, complete captcha/TOS if required.
- When the CLI resumes, choose a **profile name** (default is derived from the agent name).  
  Files created:
  - `~/.config/bds-agent/profiles/<profile>.json` — API key, org id, metering base URL  
  - `~/.config/bds-agent/active_profile` — so later commands know which profile is active  

**Duplicate email:** if this email already has an active API key on the server, **`POST /signup/initiate`** returns **409** — use your existing profile or contact support.

### 2. Check free tier

```bash
poetry run bds-agent credits balance
# or, if you use multiple profiles:
poetry run bds-agent credits balance --profile <profile>
```

### 3. (Optional) Preview pricing

No API key required for plans (only the metering URL):

```bash
poetry run bds-agent credits plans
```

Each **top-up** buys **one plan** (e.g. one payment of `tempo_amount` → `credits` for that row). Repeat **`credits topup`** for another purchase.

### 4. Configure Tempo wallet (per profile)

Tempo config is **per profile**: `~/.config/bds-agent/profiles/<profile>.tempo.env`. It is **only** used to **pay** for credits; **`/mpp/...` data requests** use the **API key** only.

```bash
poetry run bds-agent credits setup-tempo --profile <profile>
```

- Enter **private key** (hex).  
- **TEMPO_RPC_URL** and **TEMPO_CHAIN_ID** default from **`GET /credits/plans`** when the service is reachable; otherwise Moderato defaults are offered. Press Enter to accept the shown default.

Fund this wallet with the plan’s token on the correct chain before **`topup`**.

### 5. Buy credits (Tempo)

```bash
poetry run bds-agent credits topup --profile <profile>
```

The CLI submits an on-chain payment for the selected plan, then registers the tx with the metering service. On success, balance increases.

### 6. Confirm balance

```bash
poetry run bds-agent credits balance --profile <profile>
```

## Profiles and flags

| Mechanism | Effect |
|-----------|--------|
| `active_profile` file | Default profile when you omit `--profile` |
| `--profile` / `-P` on **`bds-agent`** or **`bds-agent credits …`** | Override for that invocation |
| `BDS_AGENT_PROFILE` | Same as `--profile` when set in the environment |

## Dev-only top-up (no chain)

If the metering server has **`DEV_TOPUP_SECRET`** set:

```bash
poetry run bds-agent credits topup --amount 5 --dev-secret <secret>
```

`--amount` is in **credit units**, not token amount.

## Troubleshooting

| Issue | What to check |
|-------|----------------|
| No credentials | Run **`signup`**; ensure **`profiles/<profile>.json`** exists and **`active_profile`** or **`--profile`** |
| Tempo top-up fails | **`MPP_TEMPO_RECIPIENT`** on metering; wallet funded; **`credits plans`** matches chain/token |
| **`--profile` not recognized** | Use **`bds-agent credits --profile NAME balance`** *or* **`bds-agent credits balance --profile NAME`** (both supported) |

## Further reading (protocol / architecture)

High-level protocol and metering design live in the **Powerloom coordination docs** (`ai-coord-docs`, **not** this repo), e.g. **`bds-mpp-integration`** — see **agent signup service** and **metering / credit plans** docs in that tree. This guide is the **operator path** for the **`bds-agent`** CLI only.
