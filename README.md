# bds-agent

Python package and CLI for building agents on **Powerloom BDS** data markets.

**Status**: `signup` and `credits` are wired to the [bds-agenthub-billing-metering](https://github.com/powerloom/bds-agenthub-billing-metering) HTTP API. `run`, **`bds-agent query`** (NL → catalog route + params), **`bds-agent create`** (NL → `agent.yaml`), and **local MCP** (`bds-agent mcp`, stdio) are implemented. Shared **LLM** layer (`bds-agent llm …`) powers **`query`** and **`create`**. The **`anthropic`** backend implements **only** the Anthropic Messages API; OpenAI- and Ollama-shaped APIs use the **`openai`** and **`ollama`** backends (see **`docs/USER_GUIDE.md`**).

**→ [docs/USER_GUIDE.md](docs/USER_GUIDE.md)** — signup, profiles, balance, Tempo top-up (path to paid credits).

**→ [docs/RULES.md](docs/RULES.md)** — declarative rule types (`min_usd`, `volume_spike`, …), snapshot contract, extension for integrators.

**→ [docs/SINKS.md](docs/SINKS.md)** — alert sinks (`stdout`, `slack`, `telegram`, …).

**→ [docs/AGENT_YAML.md](docs/AGENT_YAML.md)** — `agent.yaml` schema, **`${VAR}`** interpolation, **`auth`**, optional **`verify`** (on-chain CID vs `maxSnapshotsCid`). Example: **`examples/agent.example.yaml`**.

## Install

Install **[uv](https://docs.astral.sh/uv/)** once (standalone installer or your package manager).

### `uv tool install` (recommended — global `bds-agent` on `PATH`)

Installs the CLI like **pipx**: one command on your user **`PATH`**, usable from any directory.

```bash
cd bds-agent-py
uv tool install .
```

**After `git pull` or when local changes do not show up (CLI, MCP tools, etc.):** uv may reuse wheels and build cache when **`pyproject.toml`** version is unchanged. From the repo root run:

```bash
uv cache clean
uv tool install --force .
```

Then **restart the MCP client** (or reconnect MCP) if you use **`bds-agent mcp`**, so a new subprocess loads the new install. Check **`bds-agent --version`** and **`bds-agent --help`**.

**Alternative:** **`uv tool install --force --editable .`** links the tool to **`src/bds_agent`** in this checkout so you skip wheel rebuilds while editing; still restart MCP after code changes.

Ensure **uv’s tool binary directory** is on your **`PATH`** (often **`~/.local/bin`**; **`uv tool update-shell`** can print the right line for your shell). This keeps **MCP** spawn lines minimal, e.g. **`claude mcp add bds-agent-local -- bds-agent mcp`** (see **`docs/USER_GUIDE.md`** → Local MCP).

When the package is published to PyPI, **`uv tool upgrade bds-agent`** upgrades the tool.

### Development from a clone (no global `PATH` install)

```bash
cd bds-agent-py
uv sync
uv run bds-agent --help
uv run bds-agent --version
```

Use **`uv run bds-agent …`** for every CLI invocation, or install with **`uv tool install .`** when you want a stable **`bds-agent`** on **`PATH`**.

CLI: **[Typer](https://typer.tiangolo.com/)** + **httpx**.

Environment (many are optional depending on the command):

- **`BDS_AGENT_SIGNUP_URL`** — **Required for `bds-agent signup`** (first step) unless you pass **`--base-url`** on that command: metering service **origin** only. **Production:** `https://bds-agent-metering.powerloom.network`. **Local/dev:** e.g. `http://127.0.0.1:8787`. Not defaulted in code; saved as **`signup_base_url`** in the profile after signup (distinct from **`BDS_BASE_URL`** / snapshotter node—see **`docs/USER_GUIDE.md`**).
- `BDS_AGENT_PROFILE` — credentials profile name (file: `profiles/<name>.json` under the config dir)
- `BDS_DEV_TOPUP_SECRET` — must match server `DEV_TOPUP_SECRET` for dev-only `credits topup --amount`
- **`BDS_API_ENDPOINTS_CATALOG_JSON`** — path or URL to `endpoints.json` for route catalog (`run` / `query` / `mcp` / `create` — see guide)
- **`BDS_SOURCES_JSON`** — path to `sources.json` for GitHub-backed catalog resolution at pinned `compute.commit` (alternative to the above)
- **`BDS_BASE_URL`** — HTTP origin of the snapshotter API (public deploy: **`https://bds.powerloom.io/api`**; no trailing slash). Optional on disk: **`bds_base_url`** in **`profiles/<name>.json`** (see **`bds-agent config`**).
- **`BDS_AGENT_CATALOG_PATH_PREFIXES`** — which path prefixes from **`endpoints.json`** are used for **`query`** / **`mcp`** / **`run`** (default **`/mpp`**; see **`docs/USER_GUIDE.md`** → *Catalog path filter*).
- **`BDS_AGENT_LLM_BACKEND`** — `anthropic` / `openai` / `ollama` / … for **`bds-agent llm`**, **`query`**, and **`create`**
- **`ANTHROPIC_API_KEY`** / **`ANTHROPIC_AUTH_TOKEN`**, **`ANTHROPIC_BASE_URL`**, **`ANTHROPIC_MODEL`** — Anthropic Messages API only (`anthropic` backend)

Full tables and precedence: **[docs/USER_GUIDE.md](docs/USER_GUIDE.md)** → **API endpoint catalog** and **LLM backends**.

Credentials: **`~/.config/bds-agent/profiles/<profile>.json`** (plus **`active_profile`** after signup). Tempo wallet for **`credits topup`**: **`profiles/<profile>.tempo.env`**. Override with **`--profile`** / **`BDS_AGENT_PROFILE`**.

If you still have a single **`~/.config/bds-agent/tempo.env`**, move it to **`profiles/<your-profile>.tempo.env`** (or re-run **`credits setup-tempo`**). With no profile selected, the CLI may still read the legacy file as a fallback.

## Commands

| Command | Purpose |
|---------|---------|
| `bds-agent signup` | Device-auth flow; saves API key locally |
| `bds-agent credits balance` | Credit balance and rate limits |
| `bds-agent credits topup` | Billing link when checkout exists; dev `--amount` + `--dev-secret` on staging |
| `bds-agent run <agent.yaml>` | SSE stream → rules → sinks (see `docs/AGENT_YAML.md`) |
| `bds-agent query "…"` | NL → endpoint + params (LLM); optional **`--execute`** to call BDS — see **`docs/USER_GUIDE.md`** |
| `bds-agent create "…"` | NL → **`agent.yaml`** (LLM + validation); **`--output`** / **`-o`** optional — see **`docs/USER_GUIDE.md`** |
| `bds-agent llm status` / `setup` / `ping` | Configure and test LLM backends (`~/.config/bds-agent/llm.json`) |
| `bds-agent mcp` | MCP server on stdio: catalog → BDS HTTP tools (Bearer); set **`BDS_BASE_URL`** (or profile **`bds_base_url`**) + catalog paths — see **`docs/USER_GUIDE.md`** → *Local MCP server* → *Testing (Cursor, Claude Desktop, or Claude Code CLI)* |
| `bds-agent config init` | First-time defaults on the profile: BDS base URL + **`endpoints.json`** URL + Powerloom RPC + ProtocolState + DataMarket (for **`verify: true`**) — see **`docs/USER_GUIDE.md`** |
| `bds-agent config show` / `set` / `unset` | View or edit profile BDS fields (alternative to env exports) |

## Related

- [bds-agenthub-billing-metering](https://github.com/powerloom/bds-agenthub-billing-metering) — signup + API keys for agents
