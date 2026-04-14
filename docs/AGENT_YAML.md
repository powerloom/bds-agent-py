# `agent.yaml` reference

Validated by **`bds_agent.config.load_agent_yaml`** (Pydantic) after **`${VAR}`** substitution. Each variable uses the **environment** if set to a non-empty value, otherwise optional **profile JSON** fields (e.g. **`bds_base_url`** for **`${BDS_BASE_URL}`**) — see **`docs/USER_GUIDE.md`** → **Profile JSON: optional BDS defaults**.

## Top-level fields

| Field | Required | Notes |
|-------|----------|--------|
| **`name`** | yes | Agent label. |
| **`version`** | no | Default **`1`**. |
| **`source`** | yes | **`type`**: **`bds_stream`** \| **`bds_fetch`**; **`endpoint`**, **`base_url`**. |
| **`auth`** | yes | **`api_key`** and/or **`profile`** (see below). |
| **`rules`** | no | List of rule specs (`type` + parameters) — see **`docs/RULES.md`**. |
| **`sinks`** | no | List of sink specs — see **`docs/SINKS.md`**. |
| **`verify`** | no | Default **`false`**. When **`true`**, the runner compares each SSE **`verification.cid`** to **`ProtocolState.maxSnapshotsCid`** via JSON-RPC (requires **`verify_rpc_url`** or **`POWERLOOM_RPC_URL`** / profile **`powerloom_rpc_url`**). |
| **`verify_rpc_url`** | no | Powerloom chain JSON-RPC URL for **`eth_call`** (overrides **`POWERLOOM_RPC_URL`** env and profile **`powerloom_rpc_url`** when set). |
| **`verify_protocol_state`** | no | ProtocolState contract address (**`to`** on **`eth_call`**). Overrides **`POWERLOOM_PROTOCOL_STATE`** env, profile **`powerloom_protocol_state`**, and **`verification.protocolState`** from the stream. |
| **`verify_data_market`** | no | Powerloom **DataMarket** contract address (first argument to **`maxSnapshotsCid`** on ProtocolState; the call forwards to that market’s state — see **`ProtocolState.sol`**). Overrides **`POWERLOOM_DATA_MARKET`** env, profile **`powerloom_data_market`**, and **`verification.dataMarket`** from the stream. |
| **`lifecycle`** | no | **`reconnect`**, **`reconnect_delay`**, **`max_reconnects`** (`0` = unlimited). |

## `auth`

At least one of:

- **`api_key`**: Bearer string (often **`${BDS_API_KEY}`** or a literal).
- **`profile`**: Name of **`~/.config/bds-agent/profiles/<name>.json`** from **`bds-agent signup`**.

**Resolution** (`load_resolved_agent_config` / `resolve_api_key`): if **`api_key`** is non-empty after interpolation, it wins. Otherwise the profile file is loaded.

**`bds-agent run --profile NAME`**: applied **before** validation. Use this when the file has **`profile: ${BDS_AGENT_PROFILE}`** but you did not export that env var (the CLI value fills **`auth.profile`** and overrides YAML when there is no inline **`api_key`**).

## `source`

- **`bds_stream`**: long-lived SSE (e.g. **`/mpp/stream/allTrades`**).
- **`bds_fetch`**: polling GET (runner uses **`fetch`**).

**`base_url`**: HTTP origin of the snapshotter full node (no trailing slash), e.g. **`${BDS_BASE_URL}`**.

## Verification (`verify`, `verify_rpc_url`, `verify_protocol_state`, `verify_data_market`)

When **`verify: true`**, the runner reads **`verification`** from each stream event (same object the API documents for BDS clients). Verification uses **`ProtocolState.maxSnapshotsCid(dataMarket, projectId, epochId)`**, which reads the snapshot CID from the given **DataMarket** contract. The JSON-RPC **`eth_call`** targets **ProtocolState**; **DataMarket** is encoded as the first calldata argument. Both addresses must match the deployment you intend (wrong pair ⇒ wrong or empty CID). Checks run **concurrently** with rule evaluation (bounded concurrency); they do not block the rules/sinks pipeline.

**ProtocolState address precedence:** **`verify_protocol_state`** in YAML → **`POWERLOOM_PROTOCOL_STATE`** (env or profile **`powerloom_protocol_state`**) → **`verification.protocolState`** from the stream.

**DataMarket address precedence:** **`verify_data_market`** in YAML → **`POWERLOOM_DATA_MARKET`** (env or profile **`powerloom_data_market`**) → **`verification.dataMarket`** from the stream.

**RPC URL precedence:** **`verify_rpc_url`** in YAML → **`POWERLOOM_RPC_URL`** (env or profile **`powerloom_rpc_url`**).

If **`verify: true`** but no RPC URL is resolved, the runner prints a one-time warning and skips on-chain checks. If ProtocolState or DataMarket cannot be resolved for an event, the runner logs a warning for that epoch and skips the check.

On mismatch, the runner logs a warning and sends a synthetic alert (**`rule: verification`**) to configured sinks.

## Interpolation

Only **`${VAR}`** forms are expanded (one pass, non-recursive). For supported BDS-related names, the **active profile** supplies a default when the env var is unset or empty; otherwise the replacement is an empty string.

## Example

- **`examples/agent.example.yaml`** — minimal skeleton.
- **`examples/dex-alerts.yaml`** — DEX thresholds + stdout (for **`bds-agent run`** smoke tests).
- **`examples/dex-alerts-slack.yaml`** — same rules + **`stdout`** and **`slack`**; set env **`SLACK_WEBHOOK_URL`** to your Incoming Webhook URL.

**CLI:** `bds-agent run <config.yaml> [--profile NAME]` — **`--profile`** overrides **`auth.profile`** in the file.
