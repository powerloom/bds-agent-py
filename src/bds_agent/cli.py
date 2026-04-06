from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import httpx
import typer

from bds_agent import __version__
from bds_agent.credentials import load_credentials, save_credentials
from bds_agent.credits_api import CreditsError, credits_balance, credits_topup
from bds_agent.paths import credentials_path
from bds_agent.signup_api import SignupError, default_signup_base_url, initiate_signup, poll_until_approved

app = typer.Typer(
    name="bds-agent",
    help="Build and run agents on Powerloom BDS data markets.",
    no_args_is_help=True,
    add_completion=False,
)

credits_app = typer.Typer(help="Credit balance and top-up.")
app.add_typer(credits_app, name="credits")

_AGENT_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit(0)


@app.callback()
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """BDS agent CLI."""
    del ctx, version


def _resolve_api_base(base_url: Optional[str]) -> tuple[str, bool]:
    """Returns (base_url, from_saved_credentials)."""
    if base_url and base_url.strip():
        return base_url.strip().rstrip("/"), False
    creds = load_credentials()
    if creds and creds.get("signup_base_url"):
        return creds["signup_base_url"].rstrip("/"), True
    env = default_signup_base_url()
    if env:
        return env, False
    return "", False


@app.command("signup")
def signup_cmd(
    email: Optional[str] = typer.Option(None, "--email", "-e", help="Contact email"),
    agent_name: Optional[str] = typer.Option(
        None,
        "--agent-name",
        "-n",
        help="Label for this agent (letters, digits, _, -)",
    ),
    base_url: Optional[str] = typer.Option(
        None,
        "--base-url",
        help="Signup service URL (or set BDS_AGENT_SIGNUP_URL)",
    ),
) -> None:
    """Start device signup: you verify in a browser, then we save your API key locally."""
    base = (base_url or default_signup_base_url() or "").strip().rstrip("/")
    if not base:
        typer.echo(
            "Set --base-url or BDS_AGENT_SIGNUP_URL to your signup service (e.g. https://api.example.com).",
            err=True,
        )
        raise typer.Exit(1)

    if not email:
        email = typer.prompt("Email")
    if not agent_name:
        agent_name = typer.prompt("Agent name")

    email = email.strip()
    agent_name = agent_name.strip()
    if "@" not in email or len(email) > 254:
        typer.echo("Invalid email.", err=True)
        raise typer.Exit(1)
    if not _AGENT_NAME_RE.match(agent_name):
        typer.echo(
            "Agent name must be 1–64 characters: letters, digits, underscore, hyphen.",
            err=True,
        )
        raise typer.Exit(1)

    with httpx.Client(timeout=30.0) as client:
        try:
            init = initiate_signup(client, base, email, agent_name)
        except SignupError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1)

        token = init.get("session_token")
        if not isinstance(token, str) or not token.strip():
            typer.echo("Invalid response: missing session_token.", err=True)
            raise typer.Exit(1)

        vurl = init.get("verification_url", f"{base}/verify")
        ucode = init.get("user_code", "")
        typer.echo("")
        typer.echo("1. Open this link in your browser:")
        typer.echo(f"   {vurl}")
        typer.echo("")
        typer.echo("2. Enter your user code when asked:")
        typer.echo(f"   {ucode}")
        typer.echo("")
        typer.echo("Waiting for verification (Ctrl+C to abort)…")
        typer.echo("")

        exp = init.get("expires_in")
        max_wait = float(exp) + 120.0 if isinstance(exp, (int, float)) else 920.0

        try:
            done = poll_until_approved(
                client,
                base,
                token.strip(),
                max_wait_seconds=max_wait,
            )
        except SignupError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1)

    api_key = done.get("api_key")
    if not isinstance(api_key, str) or not api_key.startswith("sk_live_"):
        typer.echo("Invalid approval payload (missing api_key).", err=True)
        raise typer.Exit(1)

    org_id = str(done.get("org_id", ""))
    save_credentials(
        {
            "api_key": api_key,
            "org_id": org_id,
            "signup_base_url": base,
        }
    )

    path = credentials_path()
    typer.echo(f"API key saved. Credentials: {path}")
    typer.echo("")
    typer.echo("Next: check credits with  bds-agent credits balance")
    typer.echo("")


@app.command("run")
def run_cmd(
    config: Optional[Path] = typer.Argument(
        None,
        help="Path to agent.yaml",
    ),
) -> None:
    """Run an agent from a declarative config (coming soon)."""
    del config
    typer.echo(
        "bds-agent run: not implemented yet. "
        "See mpp-bds-client (e.g. alert_agent.py) for a working BDS client example.",
        err=True,
    )
    raise typer.Exit(1)


@app.command("create")
def create_cmd(
    prompt: Optional[str] = typer.Argument(
        None,
        help="Natural-language description of what the agent should do",
    ),
) -> None:
    """Generate agent.yaml from a prompt via LLM (coming soon)."""
    del prompt
    typer.echo(
        "bds-agent create: not implemented yet.",
        err=True,
    )
    raise typer.Exit(1)


@credits_app.command("balance")
def credits_balance_cmd(
    base_url: Optional[str] = typer.Option(
        None,
        "--base-url",
        help="Signup service URL (default: saved signup or BDS_AGENT_SIGNUP_URL)",
    ),
) -> None:
    """Show credit balance and rate limits for the saved API key."""
    creds = load_credentials()
    if not creds:
        typer.echo(
            f"No credentials found. Run  bds-agent signup  first. (Expected: {credentials_path()})",
            err=True,
        )
        raise typer.Exit(1)

    base, _src = _resolve_api_base(base_url)
    if not base:
        typer.echo(
            "Set --base-url or BDS_AGENT_SIGNUP_URL, or run signup so the service URL is saved.",
            err=True,
        )
        raise typer.Exit(1)

    try:
        data = credits_balance(base, creds["api_key"])
    except CreditsError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)

    bal = data.get("credit_balance")
    used = data.get("total_credits_used")
    bought = data.get("total_credits_purchased")
    org = data.get("org_id", "")
    rl = data.get("rate_limits") or {}
    typer.echo(f"Organization: {org}")
    typer.echo(f"Credit balance:  {bal}")
    typer.echo(f"Credits used (lifetime):  {used}")
    typer.echo(f"Credits purchased (lifetime):  {bought}")
    if isinstance(rl, dict):
        typer.echo(
            f"Rate limits:  {rl.get('requests_per_minute', '?')} req/min, "
            f"{rl.get('requests_per_day', '?')} req/day"
        )
    typer.echo("")


@credits_app.command("topup")
def credits_topup_cmd(
    amount: Optional[float] = typer.Option(
        None,
        "--amount",
        "-a",
        help="Dev/staging only: credits to add (requires server DEV_TOPUP_SECRET)",
    ),
    base_url: Optional[str] = typer.Option(None, "--base-url"),
    dev_secret: Optional[str] = typer.Option(
        None,
        "--dev-secret",
        envvar="BDS_DEV_TOPUP_SECRET",
        help="Must match server DEV_TOPUP_SECRET (dev/staging only)",
    ),
) -> None:
    """Top up credits (self-serve checkout when available) or dev-only instant top-up."""
    creds = load_credentials()
    if not creds:
        typer.echo(
            f"No credentials found. Run  bds-agent signup  first. ({credentials_path()})",
            err=True,
        )
        raise typer.Exit(1)

    base, _ = _resolve_api_base(base_url)
    if not base:
        typer.echo("Set --base-url or BDS_AGENT_SIGNUP_URL.", err=True)
        raise typer.Exit(1)

    if amount is not None:
        if not dev_secret:
            typer.echo(
                "Dev top-up requires --dev-secret (or BDS_DEV_TOPUP_SECRET) matching the server.",
                err=True,
            )
            raise typer.Exit(1)
        data, code = credits_topup(
            base,
            creds["api_key"],
            amount=amount,
            dev_secret=dev_secret,
        )
        if code == 200 and data:
            typer.echo(f"Added {data.get('amount_added')} credits. New balance: {data.get('credit_balance')}")
            return
        if data:
            typer.echo(str(data), err=True)
        else:
            typer.echo(f"Top-up failed (HTTP {code}).", err=True)
        raise typer.Exit(1)

    data, code = credits_topup(base, creds["api_key"])
    if code == 200 and data:
        typer.echo(str(data))
        return

    if code == 501 and isinstance(data, dict):
        msg = data.get("message", "")
        billing = data.get("billing_url", "")
        typer.echo("Self-serve credit purchase is not enabled on this server yet.")
        if msg:
            typer.echo(msg)
        if billing:
            typer.echo(f"Billing (when live): {billing}")
        typer.echo("")
        typer.echo("Staging/dev: set DEV_TOPUP_SECRET on the server and run:")
        typer.echo("  bds-agent credits topup --amount <n> --dev-secret <secret>")
        return

    if data:
        typer.echo(str(data), err=True)
    else:
        typer.echo(f"Request failed (HTTP {code}).", err=True)
    raise typer.Exit(1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
