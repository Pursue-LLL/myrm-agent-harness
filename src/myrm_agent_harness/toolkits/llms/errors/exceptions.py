"""Standardized LLM exceptions for the Harness framework.

Provides the base `MyrmLLMError` class which normalizes underlying provider
exceptions into structured, actionable errors with failover reasons and context.

Core Exceptions:
- MyrmLLMError: Base class for all LLM errors

[INPUT]
- (none)

[OUTPUT]
- MyrmLLMError: Standardized LLM Error thrown by the Harness framework.

[POS]
Standardized LLM exceptions for the Harness framework.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.llms.errors.error_types import FailoverReason


class MyrmLLMError(Exception):
    """Standardized LLM Error thrown by the Harness framework.

    This exception wraps underlying provider errors (e.g., from litellm or httpx)
    into a structured format. It is designed to be caught by the Server layer
    for localization and user-friendly presentation.

    Attributes:
        error_code: The standardized failover reason (e.g., RATE_LIMIT, BILLING).
        default_msg: A fallback English message describing the error.
        context: Dynamic context extracted from the error (e.g., {"retry_after": 30}).
        recovery_actions: Suggested actions for the user (e.g., ["wait", "top_up"]).
        original_exc: The underlying exception that caused this error.
        diagnostic_result: Optional diagnostic result dict with error_type, user_message, resolution_steps, locale.
    """

    def __init__(
        self,
        error_code: FailoverReason,
        default_msg: str,
        context: dict[str, object] | None = None,
        recovery_actions: list[str] | None = None,
        original_exc: Exception | None = None,
        diagnostic_result: dict[str, object] | None = None,
    ) -> None:
        super().__init__(default_msg)
        self.error_code = error_code
        self.default_msg = default_msg
        self.context = context or {}
        self.recovery_actions = recovery_actions or []
        self.original_exc = original_exc
        self.diagnostic_result = diagnostic_result

    def __str__(self) -> str:
        return f"[{self.error_code.value}] {self.default_msg}"
