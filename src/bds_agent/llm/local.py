from __future__ import annotations

from bds_agent.llm.exceptions import LlmBackendNotConfiguredError


class LocalGgufBackend:
    """Bundled GGUF via llama-cpp-python (planned; default small instruct model)."""

    async def complete(self, system: str, user: str) -> str:  # noqa: ARG002
        raise LlmBackendNotConfiguredError(
            "Local GGUF backend is not implemented yet. Use anthropic, openai, or ollama, "
            "or run `bds-agent llm setup` once local support ships.",
        )


def local_available() -> bool:
    return False
