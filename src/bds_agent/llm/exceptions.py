from __future__ import annotations


class LlmError(Exception):
    """Base class for LLM layer failures."""


class LlmBackendNotConfiguredError(LlmError):
    """Backend selected but missing API key, model path, or host."""


class LlmHttpError(LlmError):
    """Non-success HTTP response from an LLM provider."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
