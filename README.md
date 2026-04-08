# bds-agent

Python package and CLI for building agents on **Powerloom BDS** data markets.

**Status**: `signup` and `credits` are wired to the [bds-agenthub-billing-metering](https://github.com/powerloom/bds-agenthub-billing-metering) HTTP API. `run` and `create` are still TBD.

**→ [docs/USER_GUIDE.md](docs/USER_GUIDE.md)** — signup, profiles, balance, Tempo top-up (path to paid credits).

## Install

```bash
pip install poetry
cd bds-agent-py
poetry install
poetry run bds-agent --help
poetry run bds-agent --version
```

CLI: **[Typer](https://typer.tiangolo.com/)** + **httpx**.

Environment (optional):

- `BDS_AGENT_SIGNUP_URL` — signup service base URL (e.g. `http://127.0.0.1:8787`) if you omit `--base-url`
- `BDS_AGENT_PROFILE` — credentials profile name (file: `profiles/<name>.json` under the config dir)
- `BDS_DEV_TOPUP_SECRET` — must match server `DEV_TOPUP_SECRET` for dev-only `credits topup --amount`

Credentials: **`~/.config/bds-agent/profiles/<profile>.json`** (plus **`active_profile`** after signup). Tempo wallet for **`credits topup`**: **`profiles/<profile>.tempo.env`**. Override with **`--profile`** / **`BDS_AGENT_PROFILE`**.

If you still have a single **`~/.config/bds-agent/tempo.env`**, move it to **`profiles/<your-profile>.tempo.env`** (or re-run **`credits setup-tempo`**). With no profile selected, the CLI may still read the legacy file as a fallback.

## Commands

| Command | Purpose |
|---------|---------|
| `bds-agent signup` | Device-auth flow; saves API key locally |
| `bds-agent credits balance` | Credit balance and rate limits |
| `bds-agent credits topup` | Billing link when checkout exists; dev `--amount` + `--dev-secret` on staging |
| `bds-agent run [agent.yaml]` | Run a declarative agent (planned) |
| `bds-agent create "…"` | Prompt → `agent.yaml` (planned) |

## Related

- [bds-agenthub-billing-metering](https://github.com/powerloom/bds-agenthub-billing-metering) — signup + API keys for agents
