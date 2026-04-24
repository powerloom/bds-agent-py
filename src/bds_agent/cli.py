from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Annotated, Any, Optional

import httpx
import typer
from eth_account import Account
from rich import print as rprint

from bds_agent import __version__
from bds_agent.credentials import (
    OPTIONAL_PROFILE_BDS_KEYS,
    describe_credentials_location,
    load_credentials,
    resolve_credentials_path,
    resolve_evm_env_path,
    resolve_profile_name,
    resolve_tempo_env_path,
    save_credentials,
    set_cli_profile,
    update_profile_bds_fields,
    write_active_profile_name,
)
from bds_agent.credits_api import (
    CreditsError,
    credits_balance,
    credits_plans,
    credits_topup,
    credits_topup_onchain,
)
from bds_agent.paths import default_profile_slug, sanitize_profile_name
from bds_agent.plan_fields import (
    bundle_primary_chain_id,
    bundle_primary_recipient,
    bundle_primary_rpc_url,
    plan_chain_id,
)
from bds_agent.evm_config import load_evm_env_file, write_evm_env_file
from bds_agent.evm_erc20 import (
    is_native_value_plan_token,
    send_erc20_transfer,
    send_native_value_transfer,
)
from bds_agent.signup_api import SignupError, default_signup_base_url, initiate_signup, poll_until_approved
from bds_agent.signup_pay_api import signup_pay_claim, signup_pay_quote
from bds_agent.console_ui import (
    print_balance,
    print_config_init_skip,
    print_config_init_success,
    print_config_show,
    print_error,
    print_json_data,
    print_plan_pick_header,
    print_plans_bundle,
    print_signup_device_steps,
    print_signup_header,
    print_signup_success,
    print_tempo_saved,
    print_tempo_setup_intro,
    print_topup_501_help,
    print_topup_dev_success,
    print_topup_submitting,
    print_topup_tempo_chain_confirmed,
    print_topup_tempo_register_success,
    signup_waiting_status,
)
from bds_agent.tempo_config import write_tempo_env_file
from bds_agent.tempo_topup import load_tempo_env_file, run_tempo_topup_sync

app = typer.Typer(
    name="bds-agent",
    help="Build and run agents on Powerloom BDS data markets.",
    no_args_is_help=True,
    add_completion=False,
)

credits_app = typer.Typer(help="Credit balance and top-up.")
app.add_typer(credits_app, name="credits")

llm_app = typer.Typer(help="LLM backends for query/create (Anthropic Messages API, OpenAI, Ollama).")
app.add_typer(llm_app, name="llm")

config_app = typer.Typer(help="Store BDS defaults in the profile JSON (optional; reduces shell exports).")
app.add_typer(config_app, name="config")

_PROFILE_OPTION_HELP = (
    "Profile label: names the credentials JSON and per-profile wallet files (~/.config/bds-agent/profiles/<name>.*). "
    "Use BDS_AGENT_PROFILE or set before first sign-up. After device signup, active_profile may point here."
)


def _apply_profile_option(profile: Optional[str]) -> None:
    """Apply explicit --profile; must not clear when None (keep root/env/active)."""
    if profile is not None and str(profile).strip():
        set_cli_profile(str(profile).strip())


ProfileCliOption = Annotated[
    Optional[str],
    typer.Option(
        "--profile",
        "-P",
        help=_PROFILE_OPTION_HELP,
        envvar="BDS_AGENT_PROFILE",
    ),
]


@credits_app.callback()
def _credits_root(
    ctx: typer.Context,
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        "-P",
        help=_PROFILE_OPTION_HELP,
        envvar="BDS_AGENT_PROFILE",
    ),
) -> None:
    """Credit balance and top-up."""
    del ctx
    _apply_profile_option(profile)


_AGENT_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _ensure_profile_name_for_wallet(*, default_suggestion: str) -> str:
    """When no --profile / env / active_profile, pick a name so .evm.env / .tempo.env paths exist before API key."""
    n = resolve_profile_name()
    if n:
        return n
    if not _stdin_is_tty():
        print_error(
            "No profile selected. Set  export BDS_AGENT_PROFILE=<name>  or run:  "
            "bds-agent credits --profile <name> setup-evm  (no sign-up or JSON file required — only the name).",
        )
        raise typer.Exit(1)
    rprint(
        "[dim]First time: we only need a name for your wallet file on this machine. "
        "It does not require an API key or sign-up yet.[dim]"
    )
    raw = typer.prompt("Profile name", default=default_suggestion, show_default=True)
    raw = (raw or "").strip() or default_suggestion
    try:
        name = sanitize_profile_name(raw)
    except ValueError as exc:
        print_error(str(exc))
        raise typer.Exit(1) from exc
    set_cli_profile(name)
    write_active_profile_name(name)
    return name


def _prompt_profile_name(agent_name: str) -> str:
    """Label for saved credentials file (~/.config/bds-agent/profiles/<name>.json)."""
    default = default_profile_slug(agent_name)
    if _stdin_is_tty():
        raw = typer.prompt("Profile name", default=default, show_default=True)
    else:
        raw = default
    raw = (raw or "").strip() or default
    try:
        return sanitize_profile_name(raw)
    except ValueError as exc:
        print_error(str(exc))
        raise typer.Exit(1) from exc


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


DEFAULT_TEMPO_RPC = "https://rpc.moderato.tempo.xyz"
DEFAULT_TEMPO_CHAIN = "42431"


def _tempo_defaults_from_plans() -> tuple[str, str]:
    """RPC and chain id for prompts: GET /credits/plans when possible, else Moderato defaults."""
    base, _ = _resolve_api_base(None)
    if not base:
        return DEFAULT_TEMPO_RPC, DEFAULT_TEMPO_CHAIN
    try:
        data = credits_plans(base)
    except CreditsError:
        return DEFAULT_TEMPO_RPC, DEFAULT_TEMPO_CHAIN
    rpc = bundle_primary_rpc_url(data) or DEFAULT_TEMPO_RPC
    tid = bundle_primary_chain_id(data)
    chain = str(int(tid)) if tid is not None else DEFAULT_TEMPO_CHAIN
    return rpc, chain


def _interactive_setup_tempo() -> bool:
    """Prompt for Tempo key and RPC/chain; write profiles/<profile>.tempo.env. Returns True if saved."""
    _ensure_profile_name_for_wallet(default_suggestion="default")
    pname = resolve_profile_name()
    if not pname:
        return False
    out_path = resolve_tempo_env_path()
    if out_path is None:
        print_error("Could not resolve Tempo config path for this profile.")
        return False
    rpc_def, chain_def = _tempo_defaults_from_plans()
    print_tempo_setup_intro(pname, out_path)
    key = typer.prompt("Tempo private key (hex)", hide_input=True)
    if not key or not str(key).strip():
        print_error("No key entered.")
        return False
    rpc = typer.prompt(
        "TEMPO_RPC_URL",
        default=rpc_def,
        show_default=True,
    ).strip() or rpc_def
    chain = typer.prompt(
        "TEMPO_CHAIN_ID",
        default=chain_def,
        show_default=True,
    ).strip() or chain_def
    path = write_tempo_env_file(
        str(key).strip(),
        rpc_url=rpc or None,
        chain_id=chain or None,
        path=out_path,
    )
    print_tempo_saved(path)
    return True


def _select_plan_for_topup(bundle: dict[str, Any], plan_id: Optional[str]) -> dict[str, Any]:
    plans = [
        p
        for p in (bundle.get("plans") or [])
        if isinstance(p, dict) and p.get("active", True)
    ]
    if not plans:
        raise CreditsError("No active credit plans from the server.")
    if plan_id:
        for p in plans:
            if p.get("id") == plan_id:
                return p
        raise CreditsError(f"Unknown or inactive plan: {plan_id}")
    if len(plans) == 1:
        return plans[0]
    print_plan_pick_header(plans)
    n = typer.prompt("Select plan number", type=int)
    if n < 1 or n > len(plans):
        raise typer.Exit(1)
    return plans[n - 1]


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit(0)


@app.callback()
def _root(
    ctx: typer.Context,
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        "-P",
        help=_PROFILE_OPTION_HELP,
        envvar="BDS_AGENT_PROFILE",
    ),
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
    ctx.ensure_object(dict)
    ctx.obj["profile"] = profile
    _apply_profile_option(profile)
    del version


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
    """Start device signup: verify in a browser, then save your API key under a named profile."""
    base = (base_url or default_signup_base_url() or "").strip().rstrip("/")
    if not base:
        print_error(
            "Set --base-url or BDS_AGENT_SIGNUP_URL to your signup service.",
        )
        raise typer.Exit(1)

    if not email:
        email = typer.prompt("Email")
    if not agent_name:
        agent_name = typer.prompt("Agent name")

    email = email.strip()
    agent_name = agent_name.strip()
    if "@" not in email or len(email) > 254:
        print_error("Invalid email.")
        raise typer.Exit(1)
    if not _AGENT_NAME_RE.match(agent_name):
        print_error(
            "Agent name must be 1–64 characters: letters, digits, underscore, hyphen.",
        )
        raise typer.Exit(1)

    print_signup_header(email, agent_name)

    with httpx.Client(timeout=30.0) as client:
        try:
            init = initiate_signup(client, base, email, agent_name)
        except SignupError as exc:
            print_error(str(exc))
            raise typer.Exit(1)

        token = init.get("session_token")
        if not isinstance(token, str) or not token.strip():
            print_error("Invalid response: missing session_token.")
            raise typer.Exit(1)

        vurl = init.get("verification_url", f"{base}/verify")
        ucode = init.get("user_code", "")
        print_signup_device_steps(str(vurl), str(ucode))

        exp = init.get("expires_in")
        max_wait = float(exp) + 120.0 if isinstance(exp, (int, float)) else 920.0

        try:
            with signup_waiting_status():
                done = poll_until_approved(
                    client,
                    base,
                    token.strip(),
                    max_wait_seconds=max_wait,
                )
        except SignupError as exc:
            print_error(str(exc))
            raise typer.Exit(1)

    api_key = done.get("api_key")
    if not isinstance(api_key, str) or not api_key.startswith("sk_live_"):
        print_error("Invalid approval payload (missing api_key).")
        raise typer.Exit(1)

    org_id = str(done.get("org_id", ""))
    profile_name = _prompt_profile_name(agent_name)
    saved_path = save_credentials(
        {
            "api_key": api_key,
            "org_id": org_id,
            "signup_base_url": base,
        },
        profile_name=profile_name,
    )

    print_signup_success(saved_path, org_id, profile_name=profile_name)


@app.command("signup-pay")
def signup_pay_cmd(
    profile: ProfileCliOption = None,
    base_url: Optional[str] = typer.Option(
        None,
        "--base-url",
        help="Metering base URL (default: BDS_AGENT_SIGNUP_URL or saved signup_base_url)",
    ),
    agent_name: Optional[str] = typer.Option(
        None,
        "--agent-name",
        "-n",
        help="Label for this agent (letters, digits, _, -)",
    ),
    email: Optional[str] = typer.Option(
        None,
        "--email",
        "-e",
        help="Optional; if set, must be unique (same as browser signup).",
    ),
    plan_id: str = typer.Option(..., "--plan-id", help="Plan id from GET /credits/plans"),
    chain_id: int = typer.Option(
        ...,
        "--chain-id",
        help="EIP-155 chain id (must match the plan row and your wallet network).",
    ),
    token_symbol: str = typer.Option(
        ...,
        "--token-symbol",
        help="Token symbol for that plan (see token_symbol in GET /credits/plans).",
    ),
    quote_only: bool = typer.Option(
        False,
        "--quote-only",
        help="Only call POST /signup/pay/quote and print the instructions (no transfer).",
    ),
) -> None:
    """Headless signup: get a pay quote, send the on-chain payment, then claim your API key.

    ERC-20 plans: `transfer` to the quoted recipient. Native / CGT plans: a plain value send to
    the treasury. Requires a funded wallet in profiles/<profile>.evm.env (`bds-agent credits setup-evm`).
    """
    _apply_profile_option(profile)
    if not agent_name or not str(agent_name).strip():
        agent_name = typer.prompt("Agent name")
    agent_name = str(agent_name).strip()
    if not _AGENT_NAME_RE.match(agent_name):
        print_error(
            "Agent name must be 1–64 characters: letters, digits, underscore, hyphen.",
        )
        raise typer.Exit(1)
    _ensure_profile_name_for_wallet(default_suggestion=default_profile_slug(agent_name))
    if email and ("@" not in str(email) or len(str(email)) > 254):
        print_error("Invalid email.")
        raise typer.Exit(1)
    el = (email or "").strip()
    if el:
        email = el
    else:
        email = None

    base, _ = _resolve_api_base(base_url)
    if not base:
        print_error("Set --base-url or BDS_AGENT_SIGNUP_URL, or run device signup once to save the URL.")
        raise typer.Exit(1)

    load_evm_env_file()
    pk = (os.environ.get("EVM_PRIVATE_KEY") or "").strip()
    if not pk or pk == "0x":
        pth = resolve_evm_env_path()
        hint = f" {pth}" if pth else ""
        print_error(
            f"Set EVM_PRIVATE_KEY or run: bds-agent credits setup-evm{hint} (see `bds-agent credits setup-evm --help`)."
        )
        raise typer.Exit(1)
    if not pk.startswith("0x"):
        pk = "0x" + pk

    waddr = str(Account.from_key(pk).address)

    qbody: dict[str, Any] = {
        "agent_name": agent_name,
        "plan_id": plan_id.strip(),
        "chain_id": int(chain_id),
        "token_symbol": token_symbol.strip(),
        "payer_address": waddr,
    }
    if email:
        qbody["email"] = email

    with httpx.Client(timeout=60.0) as client:
        data, code = signup_pay_quote(client, base, qbody)
    if code not in (200, 201):
        err = data.get("error", "request_failed")
        msg = data.get("message", str(data))
        print_error(f"Quote failed ({code}): {err} — {msg}")
        raise typer.Exit(1)
    sn = str(data.get("signup_nonce", "") or "")
    if not sn:
        print_error("Invalid quote response: missing signup_nonce.")
        raise typer.Exit(1)
    rpc_exec = (os.environ.get("EVM_RPC_URL") or "").strip() or str(data.get("rpc_hint", "") or "").strip()
    if not quote_only and not rpc_exec:
        print_error(
            "Set EVM_RPC_URL in the profile .evm.env (or pass a public RPC) — needed to broadcast the transfer.",
        )
        raise typer.Exit(1)
    c_hint = int(data.get("chain_id", chain_id))
    recip = str(data.get("recipient", "") or "")
    token_c = str(data.get("token_contract", "") or "")
    amt_s = str(data.get("amount_atomic", "") or "")
    pay_native = (str(data.get("payment_kind", "") or "").strip() == "native_value") or is_native_value_plan_token(
        token_c
    )
    if not recip or not amt_s:
        print_error("Invalid quote: missing recipient or amount_atomic.")
        raise typer.Exit(1)
    if not pay_native and not token_c:
        print_error("Invalid quote: missing token_contract (ERC-20 plan).")
        raise typer.Exit(1)
    try:
        amt_i = int(amt_s, 10)
    except ValueError:
        print_error("Invalid amount_atomic in quote.")
        raise typer.Exit(1)
    if pay_native:
        rprint(
            f"[bold]Pay-signup quote[/]  plan={plan_id}  chain_id={c_hint}\n"
            f"  Send {amt_s} wei (chain native / CGT) to treasury {recip}\n"
            f"  From: {waddr}  (expires: {data.get('expires_at', '')})",
        )
    else:
        rprint(
            f"[bold]Pay-signup quote[/]  plan={plan_id}  chain_id={c_hint}\n"
            f"  Send {amt_s} wei of token {token_c} to {recip}\n"
            f"  From: {waddr}  (expires: {data.get('expires_at', '')})",
        )
    if quote_only:
        rprint(
            f"[dim]Next: fund and send the transfer, then run again without --quote-only, "
            f"or call POST {base.rstrip('/')}/signup/pay/claim with signup_nonce and tx_hash.[/]",
        )
        return

    if not typer.confirm(
        "Broadcast native transfer now?" if pay_native else "Broadcast ERC-20 transfer now?",
        default=True,
    ):
        raise typer.Exit(0)
    from web3 import Web3

    w3p = Web3(Web3.HTTPProvider(rpc_exec, request_kwargs={"timeout": 5}))
    if not w3p.is_connected():
        print_error("Could not connect to EVM_RPC_URL / rpc_hint RPC.")
        raise typer.Exit(1)
    if int(w3p.eth.chain_id) != c_hint:
        print_error(
            f"RPC is chain {w3p.eth.chain_id} but the quote is for {c_hint}. Fix EVM_RPC_URL or chain.",
        )
        raise typer.Exit(1)
    try:
        if pay_native:
            txh = send_native_value_transfer(
                rpc_exec,
                pk,
                recip,
                amt_i,
                c_hint,
            )
        else:
            txh = send_erc20_transfer(
                rpc_exec,
                pk,
                token_c,
                recip,
                amt_i,
                c_hint,
            )
    except Exception as ex:
        print_error(f"Transfer failed: {ex}")
        raise typer.Exit(1)
    rprint(f"[green]tx[/] {txh}  — claiming API key…")
    with httpx.Client(timeout=120.0) as client:
        cdata, ccode = signup_pay_claim(client, base, sn, txh)
    if ccode not in (200, 201):
        err = cdata.get("error", "claim_failed")
        msg = cdata.get("message", str(cdata))
        print_error(f"Claim failed ({ccode}): {err} — {msg}")
        raise typer.Exit(1)
    api_key = cdata.get("api_key", "")
    if not isinstance(api_key, str) or not api_key.startswith("sk_live_"):
        print_error("Invalid claim response: missing api_key.")
        raise typer.Exit(1)
    org_id = str(cdata.get("org_id", ""))
    prof = resolve_profile_name()
    if not prof:
        prof = _prompt_profile_name(agent_name)
    saved = save_credentials(
        {
            "api_key": api_key,
            "org_id": org_id,
            "signup_base_url": base,
        },
        profile_name=prof,
    )
    print_signup_success(saved, org_id, profile_name=prof)


@app.command("run")
def run_cmd(
    config: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        help="Path to agent.yaml",
    ),
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        "-P",
        help=_PROFILE_OPTION_HELP + " Overrides auth.profile in the YAML.",
        envvar="BDS_AGENT_PROFILE",
    ),
) -> None:
    """Run an agent: SSE stream → rules → sinks (see docs/AGENT_YAML.md)."""
    _apply_profile_option(profile)
    from bds_agent.runner import run_agent_sync

    try:
        run_agent_sync(config, profile_override=profile)
    except KeyboardInterrupt:
        raise typer.Exit(130)


@app.command("create")
def create_cmd(
    prompt: str = typer.Argument(
        ...,
        help="Natural-language description of what the agent should do",
    ),
    backend: Optional[str] = typer.Option(
        None,
        "--backend",
        "-b",
        help="LLM backend (default: BDS_AGENT_LLM_BACKEND / llm.json / auto-detect)",
        envvar="BDS_AGENT_LLM_BACKEND",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Write agent config to this path (default: ./gen-yaml/<name>.yaml)",
    ),
) -> None:
    """Generate agent.yaml from a prompt via LLM (same backends as ``bds-agent query``)."""
    from rich.console import Console

    from bds_agent.catalog import (
        CatalogError,
        apply_agent_runtime_catalog_filter,
        resolve_catalog,
    )
    from bds_agent.create import (
        CreateError,
        agent_config_to_yaml_text,
        compile_nl_to_agent_config,
        default_output_filename,
    )
    from bds_agent.llm import LlmBackendNotConfiguredError, LlmError, resolve

    async def _run() -> None:
        try:
            catalog = resolve_catalog()
            catalog = apply_agent_runtime_catalog_filter(catalog)
        except CatalogError as exc:
            print_error(str(exc))
            raise typer.Exit(1) from exc

        try:
            llm_backend = resolve(cli_backend=backend)
        except (LlmBackendNotConfiguredError, LlmError) as exc:
            print_error(str(exc))
            raise typer.Exit(1) from exc

        try:
            cfg = await compile_nl_to_agent_config(prompt, catalog, llm_backend)
        except CreateError as exc:
            print_error(str(exc))
            raise typer.Exit(1) from exc
        except LlmError as exc:
            print_error(str(exc))
            raise typer.Exit(1) from exc

        if output is not None:
            out_path = output.expanduser().resolve()
        else:
            out_path = Path.cwd() / "gen-yaml" / default_output_filename(cfg)

        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(agent_config_to_yaml_text(cfg), encoding="utf-8")
        except OSError as exc:
            print_error(f"cannot write {out_path}: {exc}")
            raise typer.Exit(1) from exc

        c = Console(highlight=False, soft_wrap=True)
        c.print(
            f"[bold green]✓[/] Wrote [bold]{out_path}[/]\n"
            f"Run with: [bold]bds-agent run {out_path}[/]  (optional: [bold]--profile[/] NAME)",
        )

    try:
        asyncio.run(_run())
    except typer.Exit:
        raise


@app.command("query")
def query_cmd(
    text: str = typer.Argument(
        ...,
        help="Natural language question; quote multi-word phrases",
    ),
    profile: ProfileCliOption = None,
    backend: Optional[str] = typer.Option(
        None,
        "--backend",
        "-b",
        help="LLM backend (default: BDS_AGENT_LLM_BACKEND / llm.json / auto-detect)",
        envvar="BDS_AGENT_LLM_BACKEND",
    ),
    execute: bool = typer.Option(
        False,
        "--execute",
        "-x",
        help="After resolving, call the BDS API (Bearer auth, metered routes consume credits)",
    ),
    base_url: Optional[str] = typer.Option(
        None,
        "--base-url",
        help="Snapshotter origin for --execute. Overrides BDS_BASE_URL / profile bds_base_url.",
        envvar="BDS_BASE_URL",
    ),
) -> None:
    """Map natural language to a catalog endpoint + params (LLM); optionally execute the request."""
    import asyncio

    from bds_agent.catalog import (
        CatalogError,
        apply_agent_runtime_catalog_filter,
        resolve_catalog,
    )
    from bds_agent.client import BdsClientError
    from bds_agent.llm import LlmBackendNotConfiguredError, LlmError, resolve
    from bds_agent.profile_env import resolve_bds_base_url
    from bds_agent.query import QueryError, execute_resolution, translate_nl

    _apply_profile_option(profile)

    async def _run() -> None:
        try:
            catalog = resolve_catalog()
            catalog = apply_agent_runtime_catalog_filter(catalog)
        except CatalogError as exc:
            print_error(str(exc))
            raise typer.Exit(1) from exc

        try:
            llm_backend = resolve(cli_backend=backend)
        except (LlmBackendNotConfiguredError, LlmError) as exc:
            print_error(str(exc))
            raise typer.Exit(1) from exc

        try:
            resolution = await translate_nl(text, catalog, llm_backend)
        except QueryError as exc:
            print_error(str(exc))
            raise typer.Exit(1) from exc
        except LlmError as exc:
            print_error(str(exc))
            raise typer.Exit(1) from exc

        payload: dict[str, object] = {
            "path": resolution.path_template,
            "sse": resolution.sse,
            "arguments": resolution.arguments,
        }
        if resolution.rationale:
            payload["rationale"] = resolution.rationale
        print_json_data(payload)

        if not execute:
            return

        creds = load_credentials()
        if not creds or not creds.get("api_key"):
            print_error(
                "No API key in profile. Run bds-agent signup or set --profile / BDS_AGENT_PROFILE.",
            )
            raise typer.Exit(1)

        bu = resolve_bds_base_url(cli_override=base_url)
        if not bu:
            print_error(
                "Set snapshotter origin for --execute: bds-agent config set bds_base_url <url>, "
                "or BDS_BASE_URL, or --base-url.",
            )
            raise typer.Exit(1)

        try:
            result = await execute_resolution(
                resolution=resolution,
                catalog=catalog,
                base_url=bu,
                api_key=str(creds["api_key"]),
            )
        except QueryError as exc:
            print_error(str(exc))
            raise typer.Exit(1) from exc
        except BdsClientError as exc:
            print_error(str(exc))
            raise typer.Exit(1) from exc

        print_json_data(result)

    try:
        asyncio.run(_run())
    except typer.Exit:
        raise


@app.command("mcp")
def mcp_cmd(
    profile: ProfileCliOption = None,
    base_url: Optional[str] = typer.Option(
        None,
        "--base-url",
        help="Snapshotter full node origin (no trailing slash). Overrides BDS_BASE_URL env and profile bds_base_url.",
        envvar="BDS_BASE_URL",
    ),
) -> None:
    """Run an MCP server on stdio: endpoint catalog → BDS HTTP tools (Bearer auth). Logs to stderr only."""
    import logging
    import sys

    from bds_agent.catalog import (
        CatalogError,
        apply_agent_runtime_catalog_filter,
        resolve_catalog,
    )
    from bds_agent.mcp.server import run_mcp_stdio
    from bds_agent.profile_env import resolve_bds_base_url

    _apply_profile_option(profile)
    logging.basicConfig(
        level=logging.WARNING,
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
    )

    creds = load_credentials()
    if not creds or not creds.get("api_key"):
        print_error(
            "No API key in profile. Run bds-agent signup or set --profile / BDS_AGENT_PROFILE.",
        )
        raise typer.Exit(1)

    bu = resolve_bds_base_url(cli_override=base_url)
    if not bu:
        print_error(
            "Set snapshotter origin: bds-agent config set bds_base_url <url>, or BDS_BASE_URL, or --base-url.",
        )
        raise typer.Exit(1)

    try:
        catalog = resolve_catalog()
        catalog = apply_agent_runtime_catalog_filter(catalog)
    except CatalogError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    try:
        asyncio.run(
            run_mcp_stdio(
                catalog=catalog,
                base_url=bu,
                api_key=str(creds["api_key"]),
            ),
        )
    except SystemExit as e:
        raise typer.Exit(e.code) from e


@config_app.command("init")
def config_init_cmd(
    profile: ProfileCliOption = None,
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite packaged defaults for all fields this command sets (BDS + Powerloom verification).",
    ),
) -> None:
    """Set default BDS URLs and Powerloom RPC / contract addresses on the profile (first-time setup)."""
    from bds_agent.defaults import (
        DEFAULT_BDS_BASE_URL,
        DEFAULT_ENDPOINTS_CATALOG_URL,
        DEFAULT_POWERLOOM_DATA_MARKET,
        DEFAULT_POWERLOOM_PROTOCOL_STATE,
        DEFAULT_POWERLOOM_RPC_URL,
    )

    _apply_profile_option(profile)
    c = load_credentials()
    if not c or not c.get("api_key"):
        print_error("Need a profile with an api_key. Run bds-agent signup first.")
        raise typer.Exit(1)

    updates: dict[str, str] = {}
    if force or not (str(c.get("bds_base_url") or "").strip()):
        updates["bds_base_url"] = DEFAULT_BDS_BASE_URL
    if force or not (str(c.get("bds_api_endpoints_catalog_json") or "").strip()):
        updates["bds_api_endpoints_catalog_json"] = DEFAULT_ENDPOINTS_CATALOG_URL
    if force or not (str(c.get("powerloom_rpc_url") or "").strip()):
        updates["powerloom_rpc_url"] = DEFAULT_POWERLOOM_RPC_URL
    if force or not (str(c.get("powerloom_protocol_state") or "").strip()):
        updates["powerloom_protocol_state"] = DEFAULT_POWERLOOM_PROTOCOL_STATE
    if force or not (str(c.get("powerloom_data_market") or "").strip()):
        updates["powerloom_data_market"] = DEFAULT_POWERLOOM_DATA_MARKET

    if not updates:
        print_config_init_skip()
        raise typer.Exit(0)

    try:
        p = update_profile_bds_fields(updates, profile_name=profile)
    except ValueError as exc:
        print_error(str(exc))
        raise typer.Exit(1) from exc
    print_config_init_success(p, updates)


@config_app.command("show")
def config_show_cmd(profile: ProfileCliOption = None) -> None:
    """Show optional BDS fields stored on the active profile (and effective env overlay)."""
    _apply_profile_option(profile)
    from bds_agent.profile_env import get_profile_env_overlay

    c = load_credentials()
    path = resolve_credentials_path()
    if not c:
        print_error("No profile credentials. Run bds-agent signup or set --profile / BDS_AGENT_PROFILE.")
        raise typer.Exit(1)
    ak = str(c.get("api_key") or "")
    masked = f"{ak[:8]}…" if len(ak) > 8 else ("***" if ak else "(missing)")
    profile_rows: list[tuple[str, str]] = [("api_key", masked)]
    for k in OPTIONAL_PROFILE_BDS_KEYS:
        v = c.get(k)
        if isinstance(v, str) and v.strip():
            profile_rows.append((k, v.strip()))
    ov = get_profile_env_overlay()
    print_config_show(path, profile_rows, ov)


@config_app.command("set")
def config_set_cmd(
    key: str = typer.Argument(
        ...,
        help=f"One of: {', '.join(OPTIONAL_PROFILE_BDS_KEYS)}",
    ),
    value: str = typer.Argument(..., help="Value to store"),
    profile: ProfileCliOption = None,
) -> None:
    """Set an optional BDS field on the profile JSON (same keys as bds-agent config show)."""
    _apply_profile_option(profile)
    if key.strip() not in OPTIONAL_PROFILE_BDS_KEYS:
        print_error(f"Unknown key {key!r}. Allowed: {', '.join(OPTIONAL_PROFILE_BDS_KEYS)}")
        raise typer.Exit(1)
    try:
        p = update_profile_bds_fields({key.strip(): value}, profile_name=profile)
    except ValueError as exc:
        print_error(str(exc))
        raise typer.Exit(1) from exc
    typer.echo(f"Updated {p}")


@config_app.command("unset")
def config_unset_cmd(
    key: str = typer.Argument(
        ...,
        help=f"One of: {', '.join(OPTIONAL_PROFILE_BDS_KEYS)}",
    ),
    profile: ProfileCliOption = None,
) -> None:
    """Remove an optional BDS field from the profile JSON."""
    _apply_profile_option(profile)
    if key.strip() not in OPTIONAL_PROFILE_BDS_KEYS:
        print_error(f"Unknown key {key!r}. Allowed: {', '.join(OPTIONAL_PROFILE_BDS_KEYS)}")
        raise typer.Exit(1)
    try:
        p = update_profile_bds_fields({key.strip(): None}, profile_name=profile)
    except ValueError as exc:
        print_error(str(exc))
        raise typer.Exit(1) from exc
    typer.echo(f"Updated {p}")


@credits_app.command("plans")
def credits_plans_cmd(
    profile: ProfileCliOption = None,
    base_url: Optional[str] = typer.Option(
        None,
        "--base-url",
        help="Metering service URL (default: BDS_AGENT_SIGNUP_URL or saved signup_base_url)",
    ),
) -> None:
    """Show credit packages (GET /credits/plans; no API key required)."""
    _apply_profile_option(profile)
    base, _ = _resolve_api_base(base_url)
    if not base:
        print_error(
            "Set --base-url or BDS_AGENT_SIGNUP_URL (or run signup once to save the service URL).",
        )
        raise typer.Exit(1)
    try:
        data = credits_plans(base)
    except CreditsError as exc:
        print_error(str(exc))
        raise typer.Exit(1)
    print_plans_bundle(data)


@credits_app.command("setup-tempo")
def credits_setup_tempo_cmd(
    profile: ProfileCliOption = None,
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing tempo.env without asking",
    ),
) -> None:
    """Save Tempo wallet to profiles/<profile>.tempo.env (interactive; used only for credits top-up)."""
    _apply_profile_option(profile)
    _ensure_profile_name_for_wallet(default_suggestion="default")
    path = resolve_tempo_env_path()
    if path is None:
        print_error("Could not resolve Tempo config path (internal).")
        raise typer.Exit(1)
    if path.is_file() and not force:
        if _stdin_is_tty():
            if not typer.confirm(f"{path} already exists. Overwrite?", default=False):
                raise typer.Exit(0)
        else:
            print_error(f"{path} exists. Use --force to overwrite.")
            raise typer.Exit(1)
    if not _interactive_setup_tempo():
        raise typer.Exit(1)


@credits_app.command("setup-evm")
def credits_setup_evm_cmd(
    profile: ProfileCliOption = None,
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing .evm.env without asking",
    ),
) -> None:
    """Save an Ethereum private key for pay-to-signup and standard on-chain credit purchases (per profile)."""
    _apply_profile_option(profile)
    _ensure_profile_name_for_wallet(default_suggestion="default")
    path = resolve_evm_env_path()
    if path is None:
        print_error("Could not resolve EVM config path (internal).")
        raise typer.Exit(1)
    if path.is_file() and not force:
        if _stdin_is_tty():
            if not typer.confirm(f"{path} already exists. Overwrite?", default=False):
                raise typer.Exit(0)
        else:
            print_error(f"{path} exists. Use --force to overwrite.")
            raise typer.Exit(1)
    pname = resolve_profile_name() or "profile"
    rpc_def, chain_def = _tempo_defaults_from_plans()
    rprint(
        f"Used for [cyan]signup-pay[/] and on-chain top-ups on the networks in [cyan]credits plans[/]. "
        f"For [cyan]credits topup[/] (Tempo) use [cyan]credits setup-tempo[/] — that is a different wallet file. "
        f"Profile [cyan]{pname}[/] → {path}",
    )
    key = typer.prompt("EVM private key (hex)", hide_input=True)
    if not key or not str(key).strip():
        print_error("No key entered.")
        raise typer.Exit(1)
    rpc = typer.prompt(
        "EVM_RPC_URL",
        default=rpc_def,
        show_default=True,
    ).strip() or rpc_def
    chain = typer.prompt(
        "Chain ID (optional; must match the network you pay on)",
        default=chain_def,
        show_default=True,
    ).strip() or chain_def
    out = write_evm_env_file(
        str(key).strip(),
        rpc_url=rpc or None,
        chain_id=chain or None,
        path=path,
    )
    rprint(f"[green]Saved[/] {out}")


@credits_app.command("balance")
def credits_balance_cmd(
    profile: ProfileCliOption = None,
    base_url: Optional[str] = typer.Option(
        None,
        "--base-url",
        help="Signup service URL (default: saved signup or BDS_AGENT_SIGNUP_URL)",
    ),
) -> None:
    """Show credit balance and rate limits for the saved API key."""
    _apply_profile_option(profile)
    creds = load_credentials()
    if not creds:
        print_error(
            f"No credentials found. Run  bds-agent signup  first. ({describe_credentials_location()})",
        )
        raise typer.Exit(1)

    base, _src = _resolve_api_base(base_url)
    if not base:
        print_error(
            "Set --base-url or BDS_AGENT_SIGNUP_URL, or run signup so the service URL is saved.",
        )
        raise typer.Exit(1)

    try:
        data = credits_balance(base, creds["api_key"])
    except CreditsError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    print_balance(data)


@credits_app.command("topup")
def credits_topup_cmd(
    profile: ProfileCliOption = None,
    amount: Optional[float] = typer.Option(
        None,
        "--amount",
        "-a",
        help="Dev/staging only: credits to add (requires server DEV_TOPUP_SECRET)",
    ),
    plan: Optional[str] = typer.Option(
        None,
        "--plan",
        "-p",
        help="Plan id from GET /credits/plans (required when multiple plans exist)",
    ),
    base_url: Optional[str] = typer.Option(None, "--base-url"),
    dev_secret: Optional[str] = typer.Option(
        None,
        "--dev-secret",
        envvar="BDS_DEV_TOPUP_SECRET",
        help="Must match server DEV_TOPUP_SECRET (dev/staging only)",
    ),
) -> None:
    """Top up credits via Tempo (MPP ChargeIntent) or dev-only instant top-up."""
    _apply_profile_option(profile)
    creds = load_credentials()
    if not creds:
        print_error(
            f"No credentials found. Run  bds-agent signup  first. ({describe_credentials_location()})",
        )
        raise typer.Exit(1)

    base, _ = _resolve_api_base(base_url)
    if not base:
        print_error("Set --base-url or BDS_AGENT_SIGNUP_URL.")
        raise typer.Exit(1)

    if amount is not None:
        if not dev_secret:
            print_error(
                "Dev top-up requires --dev-secret (or BDS_DEV_TOPUP_SECRET) matching the server.",
            )
            raise typer.Exit(1)
        data, code = credits_topup(
            base,
            creds["api_key"],
            amount=amount,
            dev_secret=dev_secret,
        )
        if code == 200 and data:
            print_topup_dev_success(data.get("amount_added"), data.get("credit_balance"))
            return
        if data:
            print_error(str(data))
        else:
            print_error(f"Top-up failed (HTTP {code}).")
        raise typer.Exit(1)

    load_tempo_env_file()
    has_tempo_key = bool(os.environ.get("TEMPO_PRIVATE_KEY"))
    if not has_tempo_key and _stdin_is_tty():
        if typer.confirm(
            "No Tempo wallet configured for credit purchases. Configure interactively now "
            f"(writes {resolve_tempo_env_path() or 'profiles/<profile>.tempo.env'})?",
            default=True,
        ):
            if _interactive_setup_tempo():
                load_tempo_env_file()
                has_tempo_key = bool(os.environ.get("TEMPO_PRIVATE_KEY"))

    if plan is not None or has_tempo_key:
        if not has_tempo_key:
            if _stdin_is_tty() and typer.confirm(
                "Tempo wallet required for this top-up. Configure interactively now?",
                default=True,
            ):
                if _interactive_setup_tempo():
                    load_tempo_env_file()
                    has_tempo_key = bool(os.environ.get("TEMPO_PRIVATE_KEY"))
        if not has_tempo_key:
            print_error(
                "Tempo top-up requires TEMPO_PRIVATE_KEY or: bds-agent credits setup-tempo",
            )
            raise typer.Exit(1)
        try:
            bundle = credits_plans(base)
        except CreditsError as exc:
            print_error(str(exc))
            raise typer.Exit(1)
        if not bundle_primary_recipient(bundle):
            print_error(
                "This server is not configured for on-chain payments (set MPP_TEMPO_RECIPIENT or PAYMENT_CHAINS_JSON on the metering service).",
            )
            raise typer.Exit(1)
        try:
            selected = _select_plan_for_topup(bundle, plan)
        except CreditsError as exc:
            print_error(str(exc))
            raise typer.Exit(1)
        print_topup_submitting(str(selected.get("id", "")))
        try:
            tx_hash = run_tempo_topup_sync(bundle, selected)
        except Exception as exc:
            print_error(str(exc))
            raise typer.Exit(1)
        print_topup_tempo_chain_confirmed(tx_hash)
        chain_id = plan_chain_id(selected)
        data, code = credits_topup_onchain(
            base,
            creds["api_key"],
            plan_id=str(selected["id"]),
            tx_hash=tx_hash,
            chain_id=chain_id,
        )
        if code == 200 and data:
            print_topup_tempo_register_success(
                data.get("amount_added"),
                data.get("credit_balance"),
            )
            return
        if data:
            print_error(str(data))
        else:
            print_error(f"Registering credits failed (HTTP {code}).")
        raise typer.Exit(1)

    data, code = credits_topup(base, creds["api_key"])
    if code == 200 and data:
        print_json_data(data)
        return

    if code == 501 and isinstance(data, dict):
        print_topup_501_help(
            str(data.get("message", "") or ""),
            str(data.get("plans_url", "") or ""),
            str(data.get("billing_url", "") or ""),
        )
        return

    if data:
        print_error(str(data))
    else:
        print_error(f"Request failed (HTTP {code}).")
    raise typer.Exit(1)


_LLM_BACKENDS = frozenset({"anthropic", "openai", "ollama", "local", "apfel"})


@llm_app.command("status")
def llm_status_cmd() -> None:
    """Show active LLM backend and config file location."""
    from bds_agent.llm.config_io import load_llm_json
    from bds_agent.llm.ollama import OllamaBackend
    from bds_agent.llm.resolve import auto_detect_backend_name, effective_backend_name, ollama_reachable
    from bds_agent.paths import llm_json_path

    path = llm_json_path()
    typer.echo(f"llm.json: {path}  (exists: {path.is_file()})")
    eff = effective_backend_name(cli_backend=None)
    typer.echo(f"effective backend (env / file): {eff or '(none)'}")
    try:
        detected = auto_detect_backend_name()
        typer.echo(f"auto-detect: {detected}")
    except Exception as exc:
        typer.echo(f"auto-detect: (not available) {exc}")
    cfg = load_llm_json()
    if cfg and cfg.backend:
        typer.echo(f"llm.json backend field: {cfg.backend}")
    has_a = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    typer.echo(f"ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN set: {has_a}")
    typer.echo(f"BDS_AGENT_LLM_BACKEND: {os.environ.get('BDS_AGENT_LLM_BACKEND', '') or '(unset)'}")
    if (eff or "").lower() == "ollama" or (cfg and cfg.backend == "ollama"):
        ob = OllamaBackend.from_config(cfg.ollama if cfg else None)
        typer.echo(
            f"Ollama: {ob.base_url}  model={ob.model}"
            + (f"  num_ctx={ob.num_ctx}" if ob.num_ctx else "")
        )
        typer.echo(f"Ollama reachable (/api/tags): {ollama_reachable()}")


@llm_app.command("list")
def llm_list_cmd() -> None:
    """List backends and whether they appear configured."""
    from bds_agent.llm.anthropic import anthropic_api_key_from_env
    from bds_agent.llm.config_io import load_llm_json
    from bds_agent.llm.local import local_available
    from bds_agent.llm.openai import openai_api_key_from_env
    from bds_agent.llm.resolve import ollama_reachable

    cfg = load_llm_json()
    rows = [
        (
            "anthropic",
            bool(anthropic_api_key_from_env() or (cfg and cfg.anthropic and cfg.anthropic.api_key)),
        ),
        ("openai", bool(openai_api_key_from_env() or (cfg and cfg.openai and cfg.openai.api_key))),
        ("ollama", ollama_reachable()),
        ("local", local_available()),
        ("apfel", False),
    ]
    for name, ok in rows:
        typer.echo(f"  {name:12}  {'ready' if ok else 'not configured'}")


@llm_app.command("use")
def llm_use_cmd(
    backend: str = typer.Argument(..., help="anthropic | openai | ollama | local | apfel"),
) -> None:
    """Set the active backend in llm.json."""
    from bds_agent.llm.config_io import load_llm_json, save_llm_json
    from bds_agent.llm.schema import LlmJson

    b = backend.strip().lower()
    if b not in _LLM_BACKENDS:
        print_error(f"Unknown backend {backend!r}. Choose one of: {', '.join(sorted(_LLM_BACKENDS))}.")
        raise typer.Exit(1)
    cfg = load_llm_json() or LlmJson()
    cfg.backend = b
    save_llm_json(cfg)
    typer.echo(f"Active backend set to {b} (saved to llm.json).")


@llm_app.command("setup")
def llm_setup_cmd(
    backend: str = typer.Argument(
        ...,
        help="anthropic (Anthropic Messages API) | openai | ollama",
    ),
) -> None:
    """Interactive setup for an LLM backend (writes ~/.config/bds-agent/llm.json)."""
    if not _stdin_is_tty():
        print_error("setup requires an interactive terminal (TTY). Set env vars or edit llm.json manually.")
        raise typer.Exit(1)
    b = backend.strip().lower()
    if b == "anthropic":
        from bds_agent.llm.setup_interactive import setup_anthropic_interactive

        setup_anthropic_interactive()
        return
    if b == "openai":
        from bds_agent.llm.setup_interactive import setup_openai_interactive

        setup_openai_interactive()
        return
    if b == "ollama":
        from bds_agent.llm.setup_interactive import setup_ollama_interactive

        setup_ollama_interactive()
        return
    print_error("Only anthropic, openai, and ollama setup are implemented (local GGUF / apfel: coming soon).")
    raise typer.Exit(1)


@llm_app.command("ping")
def llm_ping_cmd(
    backend: Optional[str] = typer.Option(
        None,
        "--backend",
        "-b",
        help="Override backend for this call (same names as bds-agent llm use).",
    ),
) -> None:
    """Send a minimal completion request (tests API keys and base URL)."""
    from bds_agent.llm import resolve
    from bds_agent.llm.exceptions import LlmBackendNotConfiguredError, LlmError, LlmHttpError

    async def _run() -> None:
        llm = resolve(backend=backend)
        text = await llm.complete(
            "You are a connectivity test. Reply with exactly the single word: OK",
            "ping",
        )
        typer.echo(text.strip())

    try:
        asyncio.run(_run())
    except LlmBackendNotConfiguredError as exc:
        print_error(str(exc))
        raise typer.Exit(1) from exc
    except LlmHttpError as exc:
        print_error(str(exc))
        raise typer.Exit(1) from exc
    except LlmError as exc:
        print_error(str(exc))
        raise typer.Exit(1) from exc


def main() -> None:
    app()


if __name__ == "__main__":
    main()
