# Rules reference (developer)

This file is for **integrators**: other Python code, hosted services, or LLMs that emit **`agent.yaml`**. Operators using **`bds-agent signup`** only do not need it.

## Contract

- **Input**: one epoch’s **`snapshot`** object from the allTrades stream (or fetch): top-level **`tradeData`** is a map **pool address → `{ "trades": [ ... ] }`**. Each trade is the Uniswap-style dict the snapshotter emits (`tradeType`, `data.calculated_trade_amount_usd`, etc.).
- **Output**: a list of **`Alert`** (rule id, epoch, pool, message, details).
- **Entry point**: **`evaluate_snapshot(epoch, snapshot, state, rules)`** in **`bds_agent.rules`**. Build **`rules`** with **`build_rules([{ "type": "...", ... }, ...])`**. Use **`RuleState(volume_window_for_rules(rules))`** so volume windows are large enough.

Filters run before alert rules: every **`pool_filter`** must allow the pool; every **`token_filter`** must match the trades. Remaining rules run in **list order**.

## Rule types (`type` field)

| `type` | Parameters | Effect |
|--------|------------|--------|
| **`pool_filter`** | **`pools`**: list of addresses, or omit / `[]` for “all pools” | Skips pools not in the list (normalized `0x…` lowercase). |
| **`token_filter`** | **`tokens`**: list of token addresses, or `[]` for “any” | Skips the pool if no trade `data` references a listed token (`token0`, `token1`, etc.). |
| **`min_usd`** | **`threshold`** (number, or string like **`50k`**, **`$50,000`**) | Alert if any **Swap** in the epoch is ≥ threshold USD (reports largest qualifying). Parsed by **`parse_rule_float`** in **`bds_agent.rules.helpers`**. |
| **`volume_spike`** | **`multiplier`**, **`window_epochs`** (optional, default 10) | Alert if epoch swap volume ≥ **`multiplier` ×** rolling average of prior epochs (same pool). |
| **`price_move`** | **`threshold_bps`** or legacy **`max_slippage_bps`** | Alert on consecutive **Swap** sqrt price move (basis points) above threshold. |

Rule classes live under **`bds_agent.rules`**; the registry is **`RULE_REGISTRY`** in **`bds_agent.rules`**.

## Composing on top

1. **Same process**: `import bds_agent.rules`, build specs as **`dict`**, call **`evaluate_snapshot`**. Your code can wrap streams, fan out to other systems, or add rules.
2. **Custom rule**: implement **`evaluate(epoch, pool, trades, state) -> list[Alert]`**, set **`type`**, add **`from_spec(cls, dict) -> Self`**, register: **`RULE_REGISTRY["my_rule"] = MyRule`** before **`build_rules`**. Keep **`type`** stable if you persist YAML.
3. **Remote agent / LLM**: there is no separate schema service yet. The table above + **`tests/test_rules.py`** are the source of truth; **`bds-agent create`** embeds the same summary in its compiler prompt (`bds_agent.create`). Coord doc: **`bds-mpp-integration/12-agentic-framework.md`**.
