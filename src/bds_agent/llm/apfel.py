from __future__ import annotations

import sys

from bds_agent.llm.exceptions import LlmBackendNotConfiguredError


class ApfelBackend:
    """Apple Intelligence via apfel (planned; macOS only)."""

    async def complete(self, system: str, user: str) -> str:  # noqa: ARG002
        raise LlmBackendNotConfiguredError(
            "apfel (Apple Intelligence) backend is not implemented yet.",
        )


def apfel_platform_ok() -> bool:
    return sys.platform == "darwin"
