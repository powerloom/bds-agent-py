# bds-agent

Python package and CLI for building agents on **[Powerloom BDS](https://powerloom.io)** data markets — verified, epoch-based blockchain data served over metered HTTP.

## Features

- **Signup & Credits** — device-auth or wallet-funded API key provisioning against the [metering service](https://github.com/powerloom/bds-agenthub-billing-metering)
- **Run** — stream snapshots via SSE, apply declarative rules, dispatch to sinks (Slack, Telegram, Discord, webhook, stdout)
- **Query** — natural-language → catalog route + params (LLM-powered); optional `--execute` for one-shot BDS calls
- **Create** — natural-language → `agent.yaml` scaffold (LLM-powered)
- **MCP server** — stdio-based MCP exposing BDS catalog as tools for Claude, Cursor, LangGraph, CrewAI, etc.
- **LLM backends** — Anthropic, OpenAI-compatible, Ollama (local)
- **On-chain verification** — optional CID verification against `ProtocolState.maxSnapshotsCid`
- **Pulse trader** — BDS stream → Pulse signals → Uniswap V3 swaps (`bds-agent trade`; separate `.trade.env` wallet)
- **Threshold Guard** — bracket take-profit / stop-loss on BDS USD prices (`bds-agent guard`; `--enter` swaps USDC → base; same `.trade.env`)
- **USD prices** — `bds-agent prices at` / `prices token` against `/mpp/token/price/` and `/mpp/tokenPrices/all/`

## Installation

```bash
# Install using pip
pip install bds-agent

# Install using pipx (recommended for CLI use)
pipx install bds-agent

# Install using uv
uv tool install bds-agent
```

## Quick Start

```bash
# Sign up for an API key (opens browser for device-auth)
bds-agent signup

# Check your credit balance
bds-agent credits balance

# Run an agent from a YAML definition
bds-agent run agent.yaml

# Natural-language query against the BDS catalog
bds-agent query "top 5 Uniswap V3 pools by 24h volume"

# Generate an agent.yaml from a description
bds-agent create "alert me on Slack when any ETH/USDC swap exceeds $50k"

# Start the MCP server (stdio) for AI framework integration
bds-agent mcp

# Threshold Guard: spot %% TP/SL, dip re-entry, optional idle exit (ETH mainnet example)
bds-agent trade setup-evm --profile myguard
bds-agent guard run --profile myguard \
  --pool 0xE0554a476A092703abdB3Ef35c80e0D76d32939F \
  --token 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2 \
  --size 5 --take-profit-pct 0.003 --stop-loss-pct 0.002 \
  --reserve-max-minutes 30 --poll 5
```

## Available Commands

| Command | Purpose |
|---------|---------|
| `bds-agent signup` | Device-auth flow; saves API key locally |
| `bds-agent signup-pay` | Wallet-funded API key (no browser) |
| `bds-agent credits balance` | Credit balance and rate limits |
| `bds-agent credits topup` | Top up credits via billing link or on-chain |
| `bds-agent credits setup-evm` | Billing wallet → `profiles/<n>.evm.env` |
| `bds-agent trade setup-evm` | Swap wallet → `profiles/<n>.trade.env` |
| `bds-agent trade run` | Pulse trader (see `docs/TRADE.md`) |
| `bds-agent prices at` / `prices token` | USD price feed (pool-scoped or all pools) |
| `bds-agent guard run` | Threshold Guard bracket trading (see `docs/GUARD.md`) |
| `bds-agent guard enter` / `guard status` | USDC → base entry or guard state |
| `bds-agent run <agent.yaml>` | SSE stream → rules → sinks |
| `bds-agent query "…"` | NL → endpoint + params (LLM) |
| `bds-agent create "…"` | NL → `agent.yaml` (LLM + validation) |
| `bds-agent llm status / setup / ping` | Configure and test LLM backends |
| `bds-agent mcp` | MCP server on stdio |
| `bds-agent config init / show / set` | Manage per-profile BDS settings |

## Requirements

- Python 3.12 or higher

## Documentation

- [User Guide](https://github.com/powerloom/bds-agent-py/blob/main/docs/USER_GUIDE.md)
- [Pulse trader (`trade`)](https://github.com/powerloom/bds-agent-py/blob/main/docs/TRADE.md)
- [Threshold Guard (`guard`)](https://github.com/powerloom/bds-agent-py/blob/main/docs/GUARD.md)
- [USD prices (`prices`)](https://github.com/powerloom/bds-agent-py/blob/main/docs/PRICES.md)
- [Agent YAML Schema](https://github.com/powerloom/bds-agent-py/blob/main/docs/AGENT_YAML.md)
- [Rules Reference](https://github.com/powerloom/bds-agent-py/blob/main/docs/RULES.md)
- [Sinks Reference](https://github.com/powerloom/bds-agent-py/blob/main/docs/SINKS.md)
- [GitHub Repository](https://github.com/powerloom/bds-agent-py)
- [Powerloom Website](https://powerloom.io)

## License

MIT License — see [LICENSE](https://github.com/powerloom/bds-agent-py/blob/main/LICENSE) for details.

## Support

- [Report Issues](https://github.com/powerloom/bds-agent-py/issues)
- [Discord Community](https://discord.gg/powerloom)
