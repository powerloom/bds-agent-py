from __future__ import annotations

import json
import os
from typing import Any

from bds_agent.llm.schema import LlmJson
from bds_agent.paths import llm_json_path


def load_llm_json() -> LlmJson | None:
    path = llm_json_path()
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None
    return LlmJson.model_validate(_coerce_legacy(raw))


def _coerce_legacy(raw: dict[str, Any]) -> dict[str, Any]:
    """Future-proof minor shape tweaks without breaking existing files."""
    return raw


def save_llm_json(cfg: LlmJson) -> None:
    path = llm_json_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(cfg.model_dump(mode="json", exclude_none=True), indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
