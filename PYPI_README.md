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
```

## Available Commands

| Command | Purpose |
|---------|---------|
| `bds-agent signup` | Device-auth flow; saves API key locally |
| `bds-agent signup-pay` | Wallet-funded API key (no browser) |
| `bds-agent credits balance` | Credit balance and rate limits |
| `bds-agent credits topup` | Top up credits via billing link or on-chain |
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
