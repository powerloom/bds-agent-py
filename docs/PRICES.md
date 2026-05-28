# USD Price Feed — `bds-agent prices`

Reference CLI for premium BDS USD routes. Billing debits per request; monitor with `bds-agent credits usage by-endpoint`.

| Command | HTTP route |
|---------|------------|
| `prices at <token> --pool <pool>` | `GET /mpp/token/price/{token}/{pool}` |
| `prices token <token>` | `GET /mpp/tokenPrices/all/{token}` |

## Commands

```bash
# Spot price for one token in one pool (latest epoch block)
bds-agent prices at 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2 \
  --pool 0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640

# All pool prices for a token
bds-agent prices token 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2

# Historical block
bds-agent prices at 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2 \
  --pool 0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640 \
  --block 21234567

# JSON output
bds-agent prices token 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2 --json
```

Requires profile with `api_key` and `bds_base_url` (same as `bds-agent trade`).

## Related

- **Pulse** (`bds-agent trade run`) — internal consumer of this feed for the price gate
- **Threshold Guard** (`bds-agent guard run`) — polls `/mpp/token/price/...` for bracket trades
- **Future**: `bds-agent mcp` to list/call hosted MCP tool names — see Powerloom `ai-coord-docs` `bds-mpp-integration/16-bds-agent-hosted-mcp-future.md`
