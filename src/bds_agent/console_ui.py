"""Rich terminal output for human-facing CLI steps."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.rule import Rule
from rich.style import Style
from rich.table import Table
from rich.text import Text


def _out() -> Console:
    return Console(
        highlight=False,
        soft_wrap=True,
        force_terminal=(
            (sys.stdout.isatty() if sys.stdout else False)
            or bool(os.environ.get("FORCE_COLOR"))
        ),
    )


def _err() -> Console:
    return Console(
        stderr=True,
        highlight=False,
        soft_wrap=True,
        force_terminal=(
            (sys.stderr.isatty() if sys.stderr else False)
            or bool(os.environ.get("FORCE_COLOR"))
        ),
    )


def print_error(message: str) -> None:
    _err().print(f"[bold red]✗[/] {message}")


def print_json_data(data: Any) -> None:
    _out().print_json(data=data)


def print_signup_header(email: str, agent_name: str) -> None:
    c = _out()
    c.print()
    c.print(Rule("[bold bright_cyan]BDS agent signup[/]", style="cyan"))
    c.print(f"[dim]Email[/] {email}  ·  [dim]Agent[/] [bold]{agent_name}[/]")
    c.print()


def print_signup_device_steps(verification_url: str, user_code: str) -> None:
    c = _out()
    body = Group(
        Text("Open this link in your browser", style="bold"),
        Text(""),
        Text(verification_url, style=Style(link=verification_url)),
        Text(""),
        Text("Enter this code when the page asks", style="bold"),
        Text(""),
        Panel(
            Text(user_code, style="bold", justify="center"),
            box=box.ROUNDED,
            border_style="bright_magenta",
            padding=(0, 2),
            expand=False,
        ),
    )
    c.print(
        Panel(
            body,
            title="[bold]Verify your device[/]",
            subtitle="[dim]Complete verification in the browser, then return here[/]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )
    c.print()


@contextmanager
def signup_waiting_status() -> Iterator[None]:
    """Spinner while polling for device verification."""
    c = _out()
    with c.status(
        "[bold green]Waiting for you to finish in the browser…[/] [dim](Ctrl+C to cancel)[/]",
        spinner="dots",
    ):
        yield


def print_signup_success(
    cred_path: Path,
    org_id: str,
    *,
    profile_name: str | None = None,
) -> None:
    c = _out()
    c.print()
    profile_line = ""
    if profile_name:
        profile_line = f"[dim]Profile[/]  [bold]{escape(profile_name)}[/]{chr(10)}"
    c.print(
        Panel(
            Group(
                Text.from_markup(
                    "[bold green]You are signed in.[/] API key saved securely.\n"
                    f"{profile_line}"
                    f"[dim]Organization[/]  [bold]{escape(org_id or '—')}[/]\n"
                    f"[dim]Credentials[/]  [cyan]{escape(str(cred_path))}[/]"
                ),
            ),
            title="[bold green]Ready[/]",
            border_style="green",
            box=box.ROUNDED,
        )
    )
    c.print()
    c.print("[bold]What to do next[/]")
    next_rows = [
        ("[cyan]bds-agent credits balance[/]", "See free-tier balance"),
        ("[cyan]bds-agent credits plans[/]", "View pricing (no API key)"),
        ("[cyan]bds-agent credits setup-tempo[/]", "Save wallet for on-chain top-up"),
        ("[cyan]bds-agent credits topup[/]", "Buy credits (prompts if needed)"),
    ]
    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_column("Command", style="bold")
    t.add_column("Why", style="dim")
    for cmd, why in next_rows:
        t.add_row(cmd, why)
    c.print(Panel(t, border_style="dim", box=box.MINIMAL))
    if profile_name:
        c.print(
            f"[dim]This profile is active for later commands. Override with[/] "
            f"[cyan]--profile {escape(profile_name)}[/] [dim]or[/] [cyan]BDS_AGENT_PROFILE[/]."
        )
    c.print()


def print_plans_bundle(data: dict[str, Any]) -> None:
    """Pretty table for GET /credits/plans response."""
    c = _out()
    plans_raw = data.get("plans") or []
    if not isinstance(plans_raw, list):
        c.print_json(data=data)
        return

    plans = [p for p in plans_raw if isinstance(p, dict) and p.get("active", True)]
    c.print()
    c.print(Rule("[bold]Credit packages[/]", style="magenta"))

    meta = Table(show_header=False, box=None, padding=(0, 1))
    meta.add_column(style="dim")
    meta.add_column()
    if data.get("tempo_recipient"):
        meta.add_row("Pay to", str(data["tempo_recipient"]))
    if data.get("tempo_chain_id") is not None:
        meta.add_row("Chain ID", str(data["tempo_chain_id"]))
    if data.get("tempo_rpc_url"):
        meta.add_row("RPC", str(data["tempo_rpc_url"]))
    eu = data.get("epoch_unit") or {}
    if isinstance(eu, dict) and eu.get("note"):
        meta.add_row("Epochs", str(eu.get("note")))
    c.print(meta)
    c.print()

    if not plans:
        c.print("[yellow]No active plans for this deployment.[/]")
        c.print()
        return

    table = Table(box=box.ROUNDED, header_style="bold magenta", border_style="bright_black")
    table.add_column("Plan", style="cyan", no_wrap=True)
    table.add_column("Credits", justify="right")
    table.add_column("You pay", style="yellow")
    table.add_column("Summary", style="dim")

    for pl in plans:
        pid = str(pl.get("id", ""))
        credits = pl.get("credits", "")
        amt = pl.get("tempo_amount", "")
        dec = pl.get("tempo_decimals")
        pay = str(amt)
        if dec is not None:
            pay = f"{amt} (decimals {dec})"
        label = str(pl.get("label", "") or pl.get("description", ""))[:64]
        table.add_row(pid, str(credits), pay, label)

    c.print(table)
    c.print()
    c.print("[dim]Each top-up buys one plan = one on-chain payment for that row’s credits.[/]")
    c.print()


def print_balance(data: dict[str, Any]) -> None:
    c = _out()
    org = data.get("org_id", "")
    bal = data.get("credit_balance")
    used = data.get("total_credits_used")
    bought = data.get("total_credits_purchased")
    rl = data.get("rate_limits") or {}

    rows = [
        ("Organization", str(org or "—")),
        ("Balance", str(bal)),
        ("Used (lifetime)", str(used)),
        ("Purchased (lifetime)", str(bought)),
    ]
    if isinstance(rl, dict):
        rpm = rl.get("requests_per_minute", "?")
        rpd = rl.get("requests_per_day", "?")
        rows.append(("Rate limits", f"{rpm} req/min · {rpd} req/day"))

    t = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    t.add_column(style="dim", min_width=22)
    t.add_column(style="bold")

    for label, val in rows:
        t.add_row(label + " ", val)

    c.print()
    c.print(
        Panel(
            t,
            title="[bold bright_cyan]Credits[/]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )
    c.print()


def print_tempo_setup_intro(profile_name: str, dest_path: Path) -> None:
    c = _out()
    c.print()
    c.print(
        Panel(
            Markdown(
                f"Tempo wallet is **only** used for `bds-agent credits topup` (on-chain payment). "
                f"Your **BDS API key** still authorizes `/mpp/...` data requests.\n\n"
                f"**Profile:** `{escape(profile_name)}` — config file:\n`{escape(str(dest_path))}`"
            ),
            border_style="blue",
            box=box.ROUNDED,
        )
    )
    c.print()


_CONFIG_FIELD_LABELS: dict[str, str] = {
    "api_key": "API key",
    "bds_base_url": "Snapshotter base URL",
    "bds_api_endpoints_catalog_json": "Endpoints catalog (JSON)",
    "bds_sources_json": "Sources manifest (JSON)",
    "bds_market_name": "Data market name",
    "powerloom_rpc_url": "Powerloom chain JSON-RPC (verification)",
    "powerloom_protocol_state": "ProtocolState contract (verification)",
    "powerloom_data_market": "DataMarket contract (verification)",
}


def print_config_init_success(path: Path, updates: dict[str, str]) -> None:
    """Rich output after `bds-agent config init` writes defaults."""
    c = _out()
    c.print()
    c.print(Rule("[bold bright_cyan]BDS agent config[/]", style="cyan"))
    val_w = max(52, min(100, c.width - 40))
    table = Table(
        show_header=True,
        box=box.ROUNDED,
        header_style="bold cyan",
        border_style="bright_black",
        padding=(0, 1),
    )
    table.add_column("Setting", style="dim", min_width=26, no_wrap=True)
    table.add_column("Value", overflow="fold", max_width=val_w)

    for k, v in updates.items():
        label = _CONFIG_FIELD_LABELS.get(k, k)
        table.add_row(f"{label}  [dim]({k})[/]", escape(v))

    c.print(
        Panel(
            Group(
                Text.from_markup(f"[dim]Profile[/]  [cyan]{escape(str(path))}[/]"),
                Text(""),
                table,
            ),
            title="[bold green]✓ Defaults applied[/]",
            border_style="green",
            box=box.ROUNDED,
        )
    )
    c.print(
        "[dim]These values apply when the corresponding env vars are unset (see[/] "
        "[cyan]docs/USER_GUIDE.md[/][dim]). Verification fields map to[/] "
        "[cyan]POWERLOOM_RPC_URL[/][dim],[/] [cyan]POWERLOOM_PROTOCOL_STATE[/][dim],[/] "
        "[cyan]POWERLOOM_DATA_MARKET[/][dim]. Run[/] [cyan]bds-agent config show[/] [dim]to review.[/]"
    )
    c.print()


def print_config_init_skip() -> None:
    """Profile already had all fields that init would set; suggest --force."""
    c = _out()
    c.print()
    c.print(
        Panel(
            "[bold yellow]Nothing to change[/]  —  this profile already has values for every "
            "field [cyan]config init[/] would write ([cyan]bds_base_url[/], [cyan]bds_api_endpoints_catalog_json[/], "
            "[cyan]powerloom_rpc_url[/], [cyan]powerloom_protocol_state[/], [cyan]powerloom_data_market[/]).\n\n"
            "Pass [cyan]--force[/] to replace them with the packaged defaults.",
            title="[dim]bds-agent config init[/]",
            border_style="yellow",
            box=box.ROUNDED,
        )
    )
    c.print()


def print_config_show(
    path: Path | None,
    profile_rows: list[tuple[str, str]],
    overlay: dict[str, str],
) -> None:
    """Rich output for `bds-agent config show`."""
    c = _out()
    c.print()
    c.print(Rule("[bold bright_cyan]Active profile[/]", style="cyan"))

    path_line = (
        f"[cyan]{escape(str(path))}[/]"
        if path
        else "[yellow](none selected)[/]"
    )
    c.print(f"[dim]File[/]  {path_line}")
    c.print()

    val_w = max(52, min(100, c.width - 40))
    pt = Table(
        show_header=True,
        box=box.ROUNDED,
        header_style="bold",
        border_style="bright_black",
        padding=(0, 1),
    )
    pt.add_column("Field", style="dim", min_width=26, no_wrap=True)
    pt.add_column("Value", overflow="fold", max_width=val_w)
    for key, val in profile_rows:
        label = _CONFIG_FIELD_LABELS.get(key, key)
        pt.add_row(f"{label}  [dim]({escape(key)})[/]", escape(val))

    c.print(
        Panel(
            pt,
            title="[bold]Stored in profile[/]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )
    c.print()

    c.print(
        Rule(
            "[dim]Environment overlay[/]  [dim italic](profile fills env when unset or empty)[/]",
            style="dim",
        )
    )
    if not overlay:
        c.print("[dim]  (no BDS_* keys from profile — export vars or use config set)[/]")
    else:
        ot = Table(
            show_header=True,
            box=box.SIMPLE,
            header_style="bold dim",
            padding=(0, 1),
        )
        ot.add_column("Variable", style="cyan", no_wrap=True)
        ot.add_column("Value", overflow="fold")
        for ek, ev in sorted(overlay.items()):
            ot.add_row(ek, escape(ev))
        c.print(ot)
    c.print()


def print_tempo_saved(path: Path) -> None:
    c = _out()
    c.print(f"[bold green]✓[/] Saved wallet config  [cyan]{path}[/]")


def print_plan_pick_header(plans: list[dict[str, Any]]) -> None:
    c = _out()
    c.print()
    c.print("[bold]Choose a package[/]")
    table = Table(show_header=True, box=box.SIMPLE, header_style="bold")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Plan", style="cyan")
    table.add_column("Label", style="dim")
    for i, p in enumerate(plans):
        table.add_row(str(i + 1), str(p.get("id", "")), str(p.get("label", "")))
    c.print(table)
    c.print()


def print_topup_dev_success(amount_added: Any, new_balance: Any) -> None:
    c = _out()
    c.print()
    c.print(
        f"[bold green]✓[/] Added [bold]{amount_added}[/] credits  →  balance [bold cyan]{new_balance}[/]"
    )
    c.print()


def print_topup_tempo_register_success(amount_added: Any, new_balance: Any) -> None:
    c = _out()
    c.print()
    c.print(
        Panel(
            f"[bold green]Credits added[/]  [bold]+{amount_added}[/]  →  balance [bold cyan]{new_balance}[/]",
            border_style="green",
            box=box.ROUNDED,
        )
    )
    c.print()


def print_topup_tempo_chain_confirmed(tx_hash: str) -> None:
    c = _out()
    c.print(f"[bold green]✓[/] On-chain payment confirmed  [dim]{tx_hash}[/]")


def print_topup_submitting(plan_id: str) -> None:
    c = _out()
    c.print(f"[bold]Submitting payment[/] for plan [cyan]{plan_id}[/] …")


def print_topup_501_help(
    msg: str,
    plans_url: str,
    billing: str,
) -> None:
    c = _out()
    c.print()
    c.print(
        Panel(
            "[bold]On-chain top-up is not available[/] from this endpoint yet.",
            border_style="yellow",
            box=box.ROUNDED,
        )
    )
    if msg:
        c.print(f"[dim]{escape(msg)}[/]")
    if plans_url:
        c.print(f"[dim]Plans URL:[/] {plans_url}")
    if billing:
        c.print(f"[dim]Billing:[/] {billing}")
    c.print()
    c.print("[bold]When Tempo is configured on the server:[/]")
    steps = Table(show_header=False, box=None)
    steps.add_column(style="cyan")
    steps.add_column()
    steps.add_row("1.", "bds-agent credits setup-tempo   # or set TEMPO_PRIVATE_KEY")
    steps.add_row("2.", "bds-agent credits topup")
    steps.add_row("—", "bds-agent credits plans   # preview pricing")
    steps.add_row("—", "bds-agent credits topup --amount N --dev-secret …   # dev/staging only")
    c.print(steps)
    c.print()
