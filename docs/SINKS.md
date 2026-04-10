# Sinks reference (developer)

Where **rules** produce **`Alert`** objects, **sinks** deliver them. All sinks implement **`async def send(alert)`**.

## Types (`type` field)

| `type` | Parameters | Behavior |
|--------|------------|----------|
| **`stdout`** | none | Rich-formatted lines to stdout. |
| **`slack`** | **`webhook_url`** | Slack Incoming Webhook, `text` payload. |
| **`telegram`** | **`bot_token`**, **`chat_id`** | `sendMessage` API. |
| **`discord`** | **`webhook_url`** | Webhook `content` (Markdown). |
| **`webhook`** | **`url`** | POST JSON: `rule`, `epoch`, `pool_address`, `message`, `details`. |

Build from YAML-style dicts: **`bds_agent.sinks.build_sink`**, **`build_sinks`**. Fan-out: **`dispatch_all(sinks, alert)`**.

Custom sinks: implement **`send`**, set **`type`**, register on **`SINK_REGISTRY`**, then **`build_sinks`** as usual.
