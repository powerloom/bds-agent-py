from __future__ import annotations

import os
import time
from typing import Any

import httpx


class SignupError(Exception):
    """Signup flow failed."""


DEFAULT_SIGNUP_BASE_URL = "https://bds-metering.powerloom.io"


def default_signup_base_url() -> str | None:
    u = os.environ.get("BDS_AGENT_SIGNUP_URL", "").strip()
    if u:
        return u.rstrip("/")
    return DEFAULT_SIGNUP_BASE_URL


def initiate_signup(client: httpx.Client, base_url: str, email: str, agent_name: str) -> dict[str, Any]:
    base = base_url.rstrip("/")
    r = client.post(
        f"{base}/signup/initiate",
        json={"email": email, "agent_name": agent_name},
    )
    if r.status_code == 429:
        ra = r.headers.get("Retry-After", "60")
        raise SignupError(f"Rate limited. Retry after {ra} seconds.")
    if r.status_code == 409:
        try:
            detail = r.json()
            if isinstance(detail, dict):
                msg = detail.get("message") or detail.get("error", "Email already registered")
                raise SignupError(str(msg))
        except SignupError:
            raise
        except Exception:
            pass
        raise SignupError("This email is already registered.")
    if r.status_code not in (200, 201):
        try:
            detail = r.json()
        except Exception:
            detail = r.text
        raise SignupError(f"signup/initiate failed ({r.status_code}): {detail}")
    data = r.json()
    if not isinstance(data, dict):
        raise SignupError("Invalid response from signup/initiate")
    return data


def poll_until_approved(
    client: httpx.Client,
    base_url: str,
    session_token: str,
    *,
    poll_seconds: float = 2.0,
    max_wait_seconds: float | None = None,
) -> dict[str, Any]:
    base = base_url.rstrip("/")
    limit = max_wait_seconds if max_wait_seconds is not None else 900.0
    deadline = time.monotonic() + limit

    while True:
        if time.monotonic() > deadline:
            raise SignupError(
                "Timed out waiting for verification. Open the URL, enter the code, then run: bds-agent signup"
            )

        r = client.get(f"{base}/signup/status", params={"session_token": session_token})
        if r.status_code == 429:
            try:
                retry = int(r.headers.get("Retry-After", "3"))
            except ValueError:
                retry = 3
            time.sleep(max(1, min(retry, 60)))
            continue

        if r.status_code == 404:
            try:
                err = r.json().get("error", "")
            except Exception:
                err = ""
            if err == "not_found":
                raise SignupError(
                    "Session not found or the API key was already delivered. "
                    "If signup finished, your key is saved in the credentials file."
                )
            raise SignupError(f"signup/status failed (404): {r.text}")

        if r.status_code != 200:
            try:
                detail = r.json()
            except Exception:
                detail = r.text
            raise SignupError(f"signup/status failed ({r.status_code}): {detail}")

        data = r.json()
        if not isinstance(data, dict):
            raise SignupError("Invalid JSON from signup/status")

        status = data.get("status")
        if status == "pending":
            time.sleep(poll_seconds)
            continue

        if status == "expired":
            raise SignupError("Signup session expired. Run signup again.")

        if status == "approved":
            return data

        raise SignupError(f"Unexpected status from server: {data!r}")
