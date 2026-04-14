"""
Run an agent: load ``agent.yaml``, SSE stream, rules → sinks.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from rich.console import Console

if TYPE_CHECKING:
    from bds_agent.config import AgentConfig

from bds_agent.catalog import agent_runtime_path_prefixes
from bds_agent.client import BdsClientError, stream
from bds_agent.config import ConfigError, effective_lifecycle, load_resolved_agent_config
from bds_agent.rules import RuleState, build_rules, evaluate_snapshot, volume_window_for_rules
from bds_agent.rules.state import Alert
from bds_agent.sinks import build_sinks, dispatch_all
from bds_agent.verify import (
    VerifyError,
    parse_verification,
    resolve_verify_data_market,
    resolve_verify_protocol_state,
    resolve_verify_rpc_url,
    verify_cid,
)

_VERIFY_CONCURRENCY = 5


@asynccontextmanager
async def _optional_verify_http(cfg: AgentConfig, rpc_url: str | None):
    if cfg.verify and rpc_url:
        async with httpx.AsyncClient(timeout=60.0) as c:
            yield c
    else:
        yield None


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

    rpc_url = resolve_verify_rpc_url(cfg) if cfg.verify else None
    if cfg.verify and not rpc_url:
        out.print(
            "[yellow]verify[/] verify: true but no RPC URL "
            "(set verify_rpc_url or POWERLOOM_RPC_URL / profile powerloom_rpc_url); skipping on-chain checks",
        )

    verify_sem = asyncio.Semaphore(_VERIFY_CONCURRENCY) if (cfg.verify and rpc_url) else None
    bg_tasks: set[asyncio.Task] = set()

    async def _verify_one(
        epoch_i: int,
        snapshot: dict,
        vp,
        verify_http: httpx.AsyncClient,
    ) -> None:
        assert verify_sem is not None
        assert rpc_url
        async with verify_sem:
            try:
                ps = resolve_verify_protocol_state(cfg, vp)
                if not ps:
                    out.print(f"[yellow]verify[/] epoch {epoch_i}: no protocol state address")
                    return
                dm = resolve_verify_data_market(cfg, vp)
                if not dm:
                    out.print(f"[yellow]verify[/] epoch {epoch_i}: no data market address")
                    return
                result = await verify_cid(
                    vp,
                    rpc_url=rpc_url,
                    protocol_state=ps,
                    data_market=dm,
                    client=verify_http,
                )
            except VerifyError as e:
                out.print(f"[yellow]verify[/] epoch {epoch_i} RPC error: {e}")
                return
        if result.match:
            out.print(f"[dim]verify[/] epoch {epoch_i} CID ok")
            return
        out.print(
            f"[yellow]verify[/] epoch {epoch_i} [bold]CID mismatch[/] "
            f"stream={result.stream_cid!r} chain={result.on_chain_cid!r} status={result.status}",
        )
        pool = ""
        if isinstance(snapshot, dict):
            pool = str(
                snapshot.get("poolAddress")
                or snapshot.get("pool_address")
                or snapshot.get("pool")
                or "",
            )
        await dispatch_all(
            sinks,
            Alert(
                rule="verification",
                epoch=epoch_i,
                pool_address=pool,
                message="snapshot CID does not match on-chain maxSnapshotsCid",
                details={
                    "stream_cid": result.stream_cid,
                    "on_chain_cid": result.on_chain_cid,
                    "on_chain_status": result.status,
                },
            ),
        )

    try:
        async with _optional_verify_http(cfg, rpc_url) as verify_http:
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

                if cfg.verify and rpc_url and verify_http and verify_sem:
                    vp = parse_verification(data)
                    if vp is not None:
                        t = asyncio.create_task(_verify_one(epoch_i, snapshot, vp, verify_http))
                        bg_tasks.add(t)
                        t.add_done_callback(bg_tasks.discard)

                alerts = evaluate_snapshot(epoch_i, snapshot, st, rules)
                for alert in alerts:
                    await dispatch_all(sinks, alert)

            if bg_tasks:
                await asyncio.gather(*bg_tasks, return_exceptions=True)

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
