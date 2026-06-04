# USD Price Feed — `bds-agent prices`

Reference CLI for premium BDS USD routes. Billing debits per request; monitor with `bds-agent credits usage by-endpoint`.

| Command | HTTP route |
|---------|------------|
| `prices at <token> --pool <pool>` | `GET /mpp/token/price/{token}/{pool}` (**preferred**) |
| `prices token <token>` | `GET /mpp/tokenPrices/all/{token}` (≤20 pools only) |

## Hub tokens (USDC, WETH, …)

`prices token` / `tokenPrices/all` **does not work** for USDC, WETH, and other majors with thousands of pools (API limit: 20 pools). Discover pools first, then price each pool:

```bash
curl -s -H "Authorization: Bearer $BDS_API_KEY" \
  "https://bds.powerloom.io/api/mpp/token/0xf280B16EF293D8e534e370794ef26bF312694126/pools" | jq '.pools | keys'
bds-agent prices at 0xf280B16EF293D8e534e370794ef26bF312694126 \
  --pool 0x08989C58bC6b18e8e2910815309A89DE4F1275B2
```

Pulse and Threshold Guard always use **`prices at`** (per-pool `/mpp/token/price/...`), not `prices token` on hub tokens.

## Commands

```bash
# Spot price for one token in one pool (latest epoch block)
bds-agent prices at 0xf280B16EF293D8e534e370794ef26bF312694126 \
  --pool 0x08989C58bC6b18e8e2910815309A89DE4F1275B2

# All pool prices — only when token has <= ~20 pools (not USDC/WETH)
bds-agent prices token 0xf280B16EF293D8e534e370794ef26bF312694126

# Historical block (Pulse / Guard)
bds-agent prices at 0xf280B16EF293D8e534e370794ef26bF312694126 \
  --pool 0x08989C58bC6b18e8e2910815309A89DE4F1275B2 \
  --block 25215944

# JSON output
bds-agent prices token 0xf280B16EF293D8e534e370794ef26bF312694126 --json
```

Requires profile with `api_key` and `bds_base_url` (same as `bds-agent trade`).

## Related

- **Pulse** (`bds-agent trade run`) — internal consumer of this feed for the price gate
- **Threshold Guard** (`bds-agent guard run`) — polls `/mpp/token/price/...` for spot %% bracket trades; see **`GUARD.md`**
- **Future**: `bds-agent mcp` to list/call hosted MCP tool names — see Powerloom `ai-coord-docs` `bds-mpp-integration/16-bds-agent-hosted-mcp-future.md`
