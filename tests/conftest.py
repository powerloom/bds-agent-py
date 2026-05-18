"""
Test-wide defaults.

On Linux runners (GitHub Actions, many dev containers), ``XDG_CONFIG_HOME`` may be set.
``bds_agent.paths.config_dir()`` prefers that over ``HOME``/``.config``, so tests that only
``monkeypatch`` ``HOME`` to a temp dir would otherwise read/write the wrong paths and fail CI.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _unset_xdg_config_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
