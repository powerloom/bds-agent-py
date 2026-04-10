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
| **`verify`** | no | Default **`false`** (on-chain CID checks; reserved for runner). |
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

## Interpolation

Only **`${VAR}`** forms are expanded (one pass, non-recursive). For supported BDS-related names, the **active profile** supplies a default when the env var is unset or empty; otherwise the replacement is an empty string.

## Example

- **`examples/agent.example.yaml`** — minimal skeleton.
- **`examples/dex-alerts.yaml`** — DEX thresholds + stdout (for **`bds-agent run`** smoke tests).
- **`examples/dex-alerts-slack.yaml`** — same rules + **`stdout`** and **`slack`**; set env **`SLACK_WEBHOOK_URL`** to your Incoming Webhook URL.

**CLI:** `bds-agent run <config.yaml> [--profile NAME]` — **`--profile`** overrides **`auth.profile`** in the file.
