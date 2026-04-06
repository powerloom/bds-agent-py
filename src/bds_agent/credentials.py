from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any, TypedDict

from bds_agent.paths import credentials_path


class Credentials(TypedDict, total=False):
    api_key: str
    org_id: str
    signup_base_url: str


def load_credentials(path: Path | None = None) -> Credentials | None:
    p = path or credentials_path()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    out: Credentials = {}
    for k in ("api_key", "org_id", "signup_base_url"):
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()  # type: ignore[literal-required]
    return out if "api_key" in out else None


def save_credentials(creds: Credentials, path: Path | None = None) -> None:
    p = path or credentials_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "api_key": creds["api_key"],
        "org_id": creds.get("org_id", ""),
        "signup_base_url": creds.get("signup_base_url", ""),
    }
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)
    try:
        os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
