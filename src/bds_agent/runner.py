"""
Run an agent: load ``agent.yaml``, SSE stream, rules → sinks.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from rich.console import Console

from bds_agent.catalog import agent_runtime_path_prefixes
from bds_agent.client import BdsClientError, stream
from bds_agent.config import ConfigError, effective_lifecycle, load_resolved_agent_config
from bds_agent.rules import RuleState, build_rules, evaluate_snapshot, volume_window_for_rules
from bds_agent.sinks import build_sinks, dispatch_all


async def run_agent(
    config_path: Path | str,
    *,
    profile_override: str | None = None,
    console: Console | None = None,
) -> None:
    """
    Main loop: ``bds_stream`` only (SSE). For each epoch payload, evaluate rules and dispatch alerts.
    """
    out = console or Console(highlight=False, soft_wrap=True, stderr=False)
    path = Path(config_path)
    try:
        resolved = load_resolved_agent_config(path, profile_override=profile_override)
    except ConfigError as e:
        out.print(f"[red]config[/] {e}")
        raise SystemExit(1) from e

    cfg = resolved.config
    api_key = resolved.api_key

    if cfg.source.type != "bds_stream":
        out.print("[red]only source.type: bds_stream is supported[/] (bds_fetch not implemented).")
        raise SystemExit(1)

    try:
        rules = build_rules(cfg.rules)
        sinks = build_sinks(cfg.sinks)
    except ValueError as e:
        out.print(f"[red]rules/sinks[/] {e}")
        raise SystemExit(1) from e

    if not sinks:
        out.print("[yellow]warning[/] no sinks configured; alerts are computed but not delivered")

    st = RuleState(volume_window_for_rules(rules))
    lc = effective_lifecycle(cfg)

    base = cfg.source.base_url.rstrip("/")
    endpoint = cfg.source.endpoint

    prefs = agent_runtime_path_prefixes()
    if prefs is not None and not any(
        endpoint == prefix or endpoint.startswith(prefix + "/")
        for prefix in prefs
    ):
        allowed = ", ".join(prefs)
        out.print(
            f"[red]run[/] source.endpoint must match BDS_AGENT_CATALOG_PATH_PREFIXES "
            f"({allowed}). Got {endpoint!r}. Set BDS_AGENT_CATALOG_PATH_PREFIXES=all to disable this check.",
        )
        raise SystemExit(1)

    out.print(
        f"[dim]run[/] [bold]{cfg.name}[/] stream [cyan]{endpoint}[/] @ [cyan]{base}[/]",
    )

    try:
        async for chunk in stream(
            base,
            endpoint,
            api_key,
            reconnect_delay=lc.reconnect_delay,
            max_reconnects=lc.max_reconnects,
            reconnect=lc.reconnect,
        ):
            if chunk.credit_balance is not None and chunk.credit_balance <= 0:
                out.print(
                    "[yellow]credit balance 0[/] — check metering / top-up; stream may stop soon",
                )

            data = chunk.data
            if data.get("skipped"):
                continue
            if "error" in data and "epoch" not in data:
                out.print(f"[red]stream error[/] {data!r}")
                continue

            epoch = data.get("epoch")
            snapshot = data.get("snapshot")
            if epoch is None or not isinstance(snapshot, dict):
                continue

            try:
                epoch_i = int(epoch)
            except (TypeError, ValueError):
                continue

            alerts = evaluate_snapshot(epoch_i, snapshot, st, rules)
            for alert in alerts:
                await dispatch_all(sinks, alert)

    except BdsClientError as e:
        out.print(f"[red]stream failed[/] {e}")
        raise SystemExit(1) from e
    except asyncio.CancelledError:
        raise
    except KeyboardInterrupt:
        out.print("[dim]stopped[/]")
        raise


def run_agent_sync(
    config_path: Path | str,
    *,
    profile_override: str | None = None,
) -> None:
    asyncio.run(run_agent(config_path, profile_override=profile_override))
