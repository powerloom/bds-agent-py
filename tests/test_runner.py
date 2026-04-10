from __future__ import annotations

from pathlib import Path

import pytest


def test_run_exits_on_missing_file(tmp_path: Path) -> None:
    from bds_agent.runner import run_agent_sync

    with pytest.raises(SystemExit):
        run_agent_sync(tmp_path / "does_not_exist.yaml")
