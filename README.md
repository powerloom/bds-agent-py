# bds-agent

Python package and CLI for building agents on **Powerloom BDS** data markets.

**Status**: `signup` and `credits` are wired to the [bds-agent-signup](https://github.com/powerloom/bds-agent-signup) HTTP API. `run` and `create` are still TBD.

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
- `BDS_DEV_TOPUP_SECRET` — must match server `DEV_TOPUP_SECRET` for dev-only `credits topup --amount`

Credentials are stored under the platform config dir (e.g. `~/.config/bds-agent/credentials.json` on Linux/macOS).

## Commands

| Command | Purpose |
|---------|---------|
| `bds-agent signup` | Device-auth flow; saves API key locally |
| `bds-agent credits balance` | Credit balance and rate limits |
| `bds-agent credits topup` | Billing link when checkout exists; dev `--amount` + `--dev-secret` on staging |
| `bds-agent run [agent.yaml]` | Run a declarative agent (planned) |
| `bds-agent create "…"` | Prompt → `agent.yaml` (planned) |

## Related

- [mpp-bds-client](https://github.com/powerloom/mpp-bds-client) — reference Python client for MPP + BDS
- [bds-agent-signup](https://github.com/powerloom/bds-agent-signup) — signup + API keys for agents
