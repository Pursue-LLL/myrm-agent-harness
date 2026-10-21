"""Shared types for LLM error diagnostics."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorContext:
    """Error diagnosis context for custom endpoint and model metadata."""

    model_name: str
    is_custom_endpoint: bool
    base_url: str | None = None


@dataclass(frozen=True)
class DiagnosticResult:
    """Structured LLM error diagnosis returned to callers."""

    error_type: str
    user_message: str
    resolution_steps: list[str]
    is_retryable: bool
    locale: str
