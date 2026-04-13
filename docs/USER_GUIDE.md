# bds-agent user guide: signup → credits → Tempo top-up

This document lives in the **`bds-agent-py`** repository so it ships with the CLI and stays valid for anyone who clones **this** repo alone. It does **not** reference private workspace-only paths.

## Install the CLI

| Method | Use case |
|--------|----------|
| **Poetry** | Clone the repo, **`poetry install`**, then **`poetry run bds-agent …`** (or **`poetry shell`** and run **`bds-agent`**). The executable is only on **`PATH`** inside that project’s virtualenv unless you activate it. |
| **`uv tool install`** | From the repo root: **`uv tool install .`** — installs **`bds-agent`** into uv’s tool environment and places it on your user **`PATH`** (similar to **pipx**). After **`git pull`** or when the CLI does not reflect your tree, run **`uv cache clean`** then **`uv tool install --force .`** (uv often reuses wheels/build cache when the package version is unchanged). After **any** reinstall, **restart the MCP host** if you use **`bds-agent mcp`**. Optional: **`uv tool install --force --editable .`** to load **`bds_agent`** from this checkout without rebuilding wheels while you edit. Put [uv](https://docs.astral.sh/uv/)’s tool **`bin`** on **`PATH`** (often **`~/.local/bin`**). |

**`uv tool` + MCP still stale:** Confirm **`which -a bds-agent`** — the first hit should be uv’s shim (e.g. **`~/.local/bin`**), not an older venv. Then **`uv cache clean`**, **`uv tool install --force .`**, and restart Cursor / Claude / the MCP connection.

Examples in this guide use **`poetry run bds-agent`**; if you used **`uv tool install`**, drop the **`poetry run`** prefix (e.g. **`bds-agent signup`**).

## Prerequisites

1. **Metering service** running and reachable. It must expose **`GET /credits/plans`**, signup routes, and **`POST /credits/topup`** with Tempo/EVM verification configured (`MPP_TEMPO_RECIPIENT`, RPC, chain, seeded plans as needed). See the [bds-agenthub-billing-metering](https://github.com/powerloom/bds-agenthub-billing-metering) README.
2. **Signup URL (required before `bds-agent signup` — this is always the first step):** the CLI must know the **metering service base URL** (same origin you use for signup and credits). **Powerloom production metering:** **`https://bds-agent-metering.powerloom.network`** (scheme + host only, no path). Set it with **`BDS_AGENT_SIGNUP_URL`** or **`bds-agent signup --base-url …`**. For local or self-hosted billing, use your own origin (e.g. **`http://127.0.0.1:8787`**). There is **no** default baked into the CLI—if both env and **`--base-url`** are missing, **`signup`** exits with an error. The URL you use is saved as **`signup_base_url`** in **`profiles/<profile>.json`** for later **`credits`** commands (it is **not** the same as **`bds_base_url`** / snapshotter node; set those separately, e.g. **`bds-agent config init`** after signup).
3. **On-chain top-up:** a wallet funded on the **same** chain and token as the plan (e.g. pathUSD on Moderato `42431` for the default seed plan).

## End-to-end path

### 1. Sign up (device flow)

**First step:** set the metering base URL, then run **`signup`**.

**Production (typical):**

```bash
export BDS_AGENT_SIGNUP_URL=https://bds-agent-metering.powerloom.network
poetry run bds-agent signup
```

**Same thing via flag (no env):** `bds-agent signup --base-url https://bds-agent-metering.powerloom.network`

**Local / self-hosted:** use your billing origin instead, e.g. `export BDS_AGENT_SIGNUP_URL=http://127.0.0.1:8787` or the matching **`--base-url`**.

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

### Profile JSON: optional BDS defaults (recommended)

Instead of exporting many variables in every shell, store **optional** fields on the same profile file as your API key: **`~/.config/bds-agent/profiles/<name>.json`**.

| Profile field | Same meaning as env |
|---------------|------------------------|
| **`bds_base_url`** | **`BDS_BASE_URL`** — snapshotter full node origin (no trailing slash). |
| **`bds_api_endpoints_catalog_json`** | **`BDS_API_ENDPOINTS_CATALOG_JSON`** — local path **or HTTPS URL** to `endpoints.json` (e.g. raw GitHub). |
| **`bds_sources_json`** | **`BDS_SOURCES_JSON`** — path to `sources.json`. |
| **`bds_market_name`** | **`BDS_MARKET_NAME`** — data market name when using `sources.json`. |

**Precedence (each setting):** non-empty **environment variable** wins; otherwise the **profile** value is used. This applies to **`agent.yaml`** `${VAR}` interpolation (e.g. `${BDS_BASE_URL}`) and to **`bds_agent.catalog.resolve_catalog()`**.

**CLI helpers**

| Command | Purpose |
|---------|---------|
| **`bds-agent config init`** | First-time setup: writes **`bds_base_url`** (`https://bds.powerloom.io/api`) and **`bds_api_endpoints_catalog_json`** (public raw URL for the BDS Uniswap V3 branch `endpoints.json`). Skips keys that are already set; use **`--force`** to replace. |
| **`bds-agent config show`** | Print stored BDS fields and the effective env overlay for the active profile. |
| **`bds-agent config set <field> <value>`** | Set one optional field (see table above). |
| **`bds-agent config unset <field>`** | Remove a field from the profile JSON. |

Use **`--profile`** / **`BDS_AGENT_PROFILE`** with these commands to edit a specific profile file.

## API endpoint catalog (`endpoints.json`)

The agent runtime loads a **language-agnostic JSON catalog** of BDS HTTP routes (paths, methods, params, metering flags). It is authored next to `api/router.py` in the **snapshotter-computes** repo as `api/endpoints.json` and is the single source of truth for **`bds-agent run`** (validate `source.endpoint`), **`bds-agent query`**, **`bds-agent mcp`**, and **`bds-agent create`** (`bds_agent.catalog.resolve_catalog`).

### When to set env vars or profile fields

Either **export env vars** or use **`bds-agent config set …`** (writes the profile JSON). CI and one-off runs often keep using env vars to override a developer profile.

| Variable | Purpose |
|----------|---------|
| **`BDS_API_ENDPOINTS_CATALOG_JSON`** | Local filesystem path **or HTTPS URL** to `endpoints.json` (the loader fetches JSON from URLs). Use a path for air-gapped use; a **raw GitHub URL** matches the compute branch catalog without cloning. |
| **`BDS_SOURCES_JSON`** | Path to **`curated-datamarkets/sources.json`** (or a copy). The loader selects a data market, reads **`compute.commit`**, and fetches **`api/endpoints.json`** from raw GitHub at that commit. |
| **`BDS_MARKET_NAME`** | Which **`dataMarkets[].name`** to use with `BDS_SOURCES_JSON` (default **`BDS_MAINNET_UNISWAPV3`**). |
| **`GITHUB_TOKEN`** / **`GH_TOKEN`** | Optional. Passed to raw GitHub requests if the repo or file requires authentication. |

**Resolution order** (first match wins): explicit `endpoints_path=` / `sources_path=` in code → **`BDS_API_ENDPOINTS_CATALOG_JSON`** (env, else profile **`bds_api_endpoints_catalog_json`**) → **`BDS_SOURCES_JSON`** (env, else profile **`bds_sources_json`**). Market name: argument → **`BDS_MARKET_NAME`** env → profile **`bds_market_name`** → default. If nothing matches, the loader raises an error listing these options.

**Cache:** Successful fetches are written under **`~/.config/bds-agent/cache/endpoints_<commit>.json`** so repeated runs do not hit the network every time.

**Signup and credits commands** do **not** load this catalog today; you only need these variables when using features that validate or enumerate BDS routes.

### Catalog path filter (`query`, MCP, `run`)

**`endpoints.json`** can list more routes than you want **`query`**, **MCP**, or **`run`** to use. By default the CLI **restricts the catalog** to paths under **`/mpp`** (same rule for **`agent.yaml`** `source.endpoint` when you run an agent).

| Variable | Purpose |
|----------|---------|
| **`BDS_AGENT_CATALOG_PATH_PREFIXES`** | Comma-separated path prefixes for that filtered view. **Unset** → **`/mpp`** only. **`all`** → use every route in the loaded catalog. |

How non-**`/mpp`** HTTP routes are exposed and authenticated is up to the **snapshotter / API deployment** — not configured here.

## LLM backends (`bds_agent.llm`, `bds-agent llm …`)

Used by **`bds-agent query`** and **`bds-agent create`**. Configuration is **agent-wide** (not per BDS profile): **`~/.config/bds-agent/llm.json`**.

| Mechanism | Effect |
|-----------|--------|
| **`--backend` / `-b`** on a command that supports it | Highest precedence (when wired). |
| **`BDS_AGENT_LLM_BACKEND`** | e.g. `anthropic`, `openai`, `ollama`. |
| **`llm.json`** `"backend"` field | Written by **`bds-agent llm use …`**. |
| **Auto-detect** | If nothing is set: prefers **`ANTHROPIC_API_KEY`** / **`ANTHROPIC_AUTH_TOKEN`**, then **`OPENAI_API_KEY`**, then a reachable local **Ollama** (`/api/tags`). Otherwise configure explicitly. |

### Anthropic Messages API (`anthropic` backend)

**Scope (current):** The **`anthropic`** backend implements **only** the Anthropic **Messages** API — `POST …/v1/messages`, `anthropic-version` header, `x-api-key`, response `content` blocks. It is **not** the OpenAI Chat Completions API; use backend **`openai`** or **`ollama`** for those protocols.

The client sends the base URL as the **origin only** (it appends **`/v1/messages`**).

| Variable | Purpose |
|----------|---------|
| **`ANTHROPIC_API_KEY`** | API secret (`x-api-key`). |
| **`ANTHROPIC_AUTH_TOKEN`** | Same role as **`ANTHROPIC_API_KEY`** if your environment uses this name instead (either one may be set). |
| **`ANTHROPIC_BASE_URL`** | API origin (default `https://api.anthropic.com`). |
| **`ANTHROPIC_MODEL`** | Model id (see Anthropic model names in their docs). |

**Interactive setup:** `bds-agent llm setup anthropic` (writes **`llm.json`**; file mode **0600** where supported).

**Smoke test:** `bds-agent llm ping` (sends a minimal completion).

### OpenAI-compatible

| Variable | Purpose |
|----------|---------|
| **`OPENAI_API_KEY`** | Bearer token for **`POST …/chat/completions`**. |
| **`OPENAI_BASE_URL`** | Default `https://api.openai.com/v1`. |
| **`OPENAI_MODEL`** | Model id. |

### Ollama

| Variable | Purpose |
|----------|---------|
| **`OLLAMA_HOST`** | Host or full URL (default `127.0.0.1:11434`). |
| **`OLLAMA_MODEL`** | Tag name on the server. |

### CLI reference

| Command | Purpose |
|---------|---------|
| **`bds-agent llm status`** | Show config path, effective backend, env hints. |
| **`bds-agent llm list`** | Which backends look configured. |
| **`bds-agent llm use <backend>`** | Set active backend in **`llm.json`**. |
| **`bds-agent llm setup anthropic`** | Prompt for base URL, model, API key. |
| **`bds-agent llm setup openai`** | Prompt for OpenAI-compatible endpoint. |
| **`bds-agent llm setup ollama`** | Prompt for host and model name. |
| **`bds-agent llm ping`** | One completion to verify connectivity. |

## Natural language query (`bds-agent query`)

Maps a **plain-English question** to one route from **`endpoints.json`** plus **path/query parameters** using the **shared LLM** (`bds_agent.llm`). Output is JSON on stdout: **`path`**, **`sse`**, **`arguments`**, optional **`rationale`**.

**Requirements**

| Requirement | Notes |
|-------------|--------|
| **Catalog** | Same as **`run`** / **`mcp`**: **`BDS_API_ENDPOINTS_CATALOG_JSON`** or **`BDS_SOURCES_JSON`** (+ optional **`BDS_MARKET_NAME`**) or profile fields (`config init`). |
| **LLM** | `bds-agent llm setup …` / env keys (`ANTHROPIC_API_KEY`, etc.) or **`--backend`**. |

**Flags**

| Flag | Purpose |
|------|---------|
| **`--backend` / `-b`** | LLM backend name (overrides **`BDS_AGENT_LLM_BACKEND`** / **`llm.json`**). |
| **`--execute` / `-x`** | After resolving, **call** the BDS API (Bearer + metering). Requires **profile** API key and **`BDS_BASE_URL`** (or **`--base-url`** / profile **`bds_base_url`**). Metered routes consume credits. |
| **`--profile` / `-P`** | Profile for **`--execute`** (and for consistency with other commands). |

**Examples**

```bash
poetry run bds-agent query "all trades snapshot for epoch block 12345678"
poetry run bds-agent query "stream all trades" --backend anthropic
poetry run bds-agent query "latest all-pool trades per finalized epoch" -x --base-url https://bds.powerloom.io/api
```

The model only chooses among **filtered** catalog paths (default **`/mpp`** — see **Catalog path filter** above). It must return a **`path`** that **exactly matches** a catalog entry (including `{placeholders}`). **SSE** routes default **`max_events`** to **5** if omitted. This command does **not** use MCP; it uses the same filtered catalog and HTTP stack as **`bds-agent mcp`** tools.

## Generate `agent.yaml` (`bds-agent create`)

Turns a **natural-language agent description** into a validated **`agent.yaml`** using the **same LLM stack** as **`bds-agent query`** (`bds_agent.create`: JSON Schema from **`AgentConfig`**, rule/sink summaries, **`endpoints.json`** excerpt). Output is written to disk; then run it with **`bds-agent run`**.

**Requirements**

| Requirement | Notes |
|-------------|--------|
| **Catalog** | Same as **`query`** / **`run`** / **`mcp`**: **`BDS_API_ENDPOINTS_CATALOG_JSON`** or **`BDS_SOURCES_JSON`** (+ optional **`BDS_MARKET_NAME`**) or profile fields. |
| **LLM** | **`bds-agent llm setup …`**, env keys, or **`--backend`**. |

**Flags**

| Flag | Purpose |
|------|---------|
| **`--backend` / `-b`** | LLM backend name (overrides **`BDS_AGENT_LLM_BACKEND`** / **`llm.json`**). |
| **`--output` / `-o`** | Write to this file path. Default: **`<name>.yaml`** in the current directory ( **`name`** from the generated config). |

**Examples**

```bash
poetry run bds-agent create "Alert me on stdout when any Uniswap swap exceeds $50k USD"
poetry run bds-agent create "Slack webhook alerts for volume spikes on all pools" --backend openai -o ./my-agent.yaml
```

**Note:** This command does **not** invoke MCP; it only shares the catalog and LLM backends with **`mcp`** and **`query`**.

## Local MCP server (`bds-agent mcp`)

Runs a **Model Context Protocol** server on **stdio** (for Cursor, Claude Desktop, **Claude Code** CLI, and other MCP clients). Tools are generated from the same **`endpoints.json`** catalog as **`bds-agent run`** (see **API endpoint catalog** above). Each catalog route becomes one MCP tool; **GET** snapshot routes use **`fetch`**, **SSE** routes return a bounded list of events ( **`max_events`**, default **5**, max **50**).

**Requirements**

| Requirement | Notes |
|-------------|--------|
| **Profile + API key** | Same **`Authorization: Bearer`** as **`bds-agent run`** (`--profile` / **`BDS_AGENT_PROFILE`** / **`active_profile`**). |
| **`BDS_BASE_URL`** | Snapshotter full node origin (or **`--base-url`**). Same as **`source.base_url`** in **`agent.yaml`**. |
| **Catalog env** | **`BDS_API_ENDPOINTS_CATALOG_JSON`** or **`BDS_SOURCES_JSON`** (+ optional **`BDS_MARKET_NAME`**) — same resolution as **`bds_agent.catalog.resolve_catalog`**. |

**Important:** Do not print to **stdout** from wrappers around this command — stdout is reserved for MCP JSON-RPC. The CLI logs warnings to **stderr** only.

### Testing (Cursor, Claude Desktop, or Claude Code CLI)

This server uses **stdio** only. The MCP client does **not** connect to a URL; it **starts** `bds-agent mcp` as a subprocess. There is no separate “deploy the MCP server” step beyond installing the CLI and configuring the client.

**Before you wire the client**

1. Complete **signup** so the profile has an **`api_key`**.
2. Point the profile at BDS + catalog: **`bds-agent config init`** (recommended) or set **`BDS_BASE_URL`** and **`BDS_API_ENDPOINTS_CATALOG_JSON`** / **`BDS_SOURCES_JSON`** — same as **`bds-agent run`** (see **API endpoint catalog** and **Profiles and flags** above).
3. Optional sanity check: **`bds-agent config show`** and confirm **`bds_base_url`** and catalog fields (or env overlay).

**Client configuration**

- Set **`command`** (and **`args`**) so the child process is **`bds-agent mcp`** — for example **`poetry`** with **`args`**: `["run", "bds-agent", "mcp"]` and **`cwd`** set to the **`bds-agent-py`** repository if you use Poetry.
- Pass **`env`**:
  - **Minimal:** **`BDS_AGENT_PROFILE=<profile>`** if **`config init`** (or manual **`config set`**) already stored **`bds_base_url`** and catalog URLs on that profile.
  - **Explicit:** **`BDS_BASE_URL`**, **`BDS_API_ENDPOINTS_CATALOG_JSON`** (path or HTTPS URL) or **`BDS_SOURCES_JSON`** + **`BDS_MARKET_NAME`**, plus **`BDS_AGENT_PROFILE`** as needed.

**Where to edit config**

- **Cursor:** MCP settings (project or user) — add a server that runs the command above; restart the app after changes.
- **Claude Desktop (macOS):** **`~/Library/Application Support/Claude/claude_desktop_config.json`** — **`mcpServers`** entry with **`command`**, **`args`**, **`env`**; restart Claude Desktop.
- **Claude Code CLI:** register a local MCP with **`claude mcp add`** — the name you choose appears in **`/mcp`** (e.g. **connected** + tool count). Run from a directory where env is correct, or rely on profile + **`config init`** as above.

  **Recommended** if **`bds-agent`** is on **`PATH`** (e.g. after **`uv tool install .`** — see **Install the CLI** above; use **`uv cache clean`** + **`uv tool install --force .`** when updating from a clone):

  ```bash
  claude mcp add bds-agent-local -- bds-agent mcp
  ```

  **`bds-agent-local`** is only a display label; use any name you like.

  **Without** a global **`bds-agent`**, use Poetry from the repo (absolute **`poetry`** path if pyenv shims are not visible to the Claude Code process):

  ```bash
  claude mcp add bds-agent -- /path/to/poetry run bds-agent mcp
  ```

  **`poetry run`** needs **`pyproject.toml`** in the child’s cwd unless you use the **`uv tool install`** approach.

  The project may store MCP entries in **`.claude.json`** (paths are project-scoped in the UI). After adding, **`/mcp`** should list the server as connected and expose one tool per **filtered** catalog route (see **Catalog path filter** above).

**What “success” looks like**

1. The client lists MCP tools whose names start with **`bds_`** (one tool per **filtered** catalog route). Names are derived from the path template: path parameters are folded in (e.g. **`bds_mpp_ethPrice`** vs **`bds_mpp_ethPrice_block_number`**) so variants do not collapse to duplicate **`bds_*`** / **`bds_*_2`** pairs.
2. Calling a **GET** tool returns JSON from BDS or a documented HTTP error (e.g. **402** if credits are exhausted).
3. **SSE** tools accept **`max_events`** (1–50) and return a bounded list of stream events.

If tools do not appear, verify catalog resolution and profile/env. If the client cannot start the server, verify **`command`/`cwd`**, and ensure **nothing** writes to **stdout** except the MCP process itself.

## BDS HTTP client (`bds_agent.client`)

Use the **API key** from your profile (see **Profiles and flags** above) for **`Authorization: Bearer`**.

**`BDS_BASE_URL`** is the HTTP origin (no trailing slash) of the **snapshotter full node** you call: the service that exposes the protocol resolver (timeseries / snapshot primitives) and mounts compute-module routers (FastAPI) for market-specific routes such as metered **`/mpp/...`**. Use the same origin as **`source.base_url`** in **`agent.yaml`**.

| API | Behavior |
|-----|----------|
| **`stream(...)`** | Long-lived SSE; exposes **`X-BDS-Credit-Balance`** on each connection via **`StreamChunk.credit_balance`**. |
| **`fetch(...)`** | Single GET; **`FetchResult.credit_balance`** and **`FetchResult.data`**; non-2xx responses (including **402**) raise **`BdsClientError`**. |

**`stream` reconnects:** after an error, waits **`reconnect_delay`** and retries (**`max_reconnects`**, default **0** = unlimited). After a normal end of the SSE body, failures are reset and the next connection starts without that delay.

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
| **MCP tools empty / server exits** | Catalog not resolved — set **`BDS_API_ENDPOINTS_CATALOG_JSON`** or **`BDS_SOURCES_JSON`**; ensure **`BDS_BASE_URL`** and a valid **API key** profile |
