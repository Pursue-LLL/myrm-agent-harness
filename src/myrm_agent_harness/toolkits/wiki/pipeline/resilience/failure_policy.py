"""Compile failure classification and retry/pause policy.

[INPUT]
- toolkits.llms.errors.classifier::classify_error, ErrorKind (POS: LLM error taxonomy SSOT)
- .sanitize::sanitize_display_message (POS: user-safe compile error display)
- .types::FailureResolution (POS: compile failure policy result)

[OUTPUT]
- resolve_io_failure, resolve_llm_failure, resolve_embed_failure: map failures to queue retry/pause policy
- evaluate_batch_pause: batch-level compile circuit pause decision
- is_transient_error_kind: transient retry eligibility filter
- EMBED_WINDOW_VIOLATION: embed input window error kind for compile circuit + UI

[POS]
Wiki compile failure policy. Classifies IO/LLM failures and decides retry backoff vs circuit pause.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.llms.errors.classifier import ErrorKind, classify_error
from myrm_agent_harness.toolkits.retriever.embedding.window_policy import EmbedInputTooLargeError

from .sanitize import sanitize_display_message
from .types import FailureResolution

IO_MISSING = "io_missing"
EMBED_WINDOW_VIOLATION = "embed_window_violation"

_TRANSIENT_KINDS: frozenset[str] = frozenset(
    {
        ErrorKind.RATE_LIMIT.value,
        ErrorKind.OVERLOADED.value,
        ErrorKind.TIMEOUT.value,
    }
)
_PAUSE_KINDS: frozenset[str] = frozenset(
    {
        ErrorKind.AUTH.value,
        ErrorKind.BILLING.value,
        EMBED_WINDOW_VIOLATION,
    }
)
_NON_RETRY_KINDS: frozenset[str] = frozenset(
    {
        ErrorKind.AUTH.value,
        ErrorKind.BILLING.value,
        ErrorKind.SAFETY_BLOCK.value,
        ErrorKind.CONTEXT_OVERFLOW.value,
        ErrorKind.FORMAT_ERROR.value,
        ErrorKind.RESPONSE_FORMAT_ERROR.value,
        ErrorKind.MODEL_NOT_FOUND.value,
        IO_MISSING,
        EMBED_WINDOW_VIOLATION,
    }
)

_TRANSIENT_BACKOFF_SECONDS: dict[str, int] = {
    ErrorKind.RATE_LIMIT.value: 120,
    ErrorKind.OVERLOADED.value: 60,
    ErrorKind.TIMEOUT.value: 30,
}


def resolve_io_failure(message: str) -> FailureResolution:
    """Classify non-LLM IO failures (missing file, read error)."""
    _ = message
    return FailureResolution(
        error_kind=IO_MISSING,
        retryable=False,
        counts_toward_pause=False,
    )


def resolve_embed_failure(exc: EmbedInputTooLargeError) -> tuple[str, str]:
    """Map an embed window violation to compile pause reason and error kind."""
    model_label = exc.model or "embedding model"
    scope = f" for '{exc.parent_key}'" if exc.parent_key else ""
    reason = sanitize_display_message(
        f"Embedding input {exc.token_count} tokens exceeds {model_label} limit "
        f"{exc.limit}{scope}. Switch to a larger-window embedding model, then resume."
    )
    return reason, EMBED_WINDOW_VIOLATION


def resolve_llm_failure(exc: Exception) -> FailureResolution:
    """Map an LLM exception to queue retry and circuit pause policy."""
    error_kind = classify_error(exc).value
    retryable = error_kind not in _NON_RETRY_KINDS
    backoff = _TRANSIENT_BACKOFF_SECONDS.get(error_kind, 0) if retryable else 0
    counts_toward_pause = error_kind in _TRANSIENT_KINDS or error_kind in _PAUSE_KINDS
    return FailureResolution(
        error_kind=error_kind,
        retryable=retryable,
        counts_toward_pause=counts_toward_pause,
        retry_after_seconds=backoff,
    )


def is_transient_error_kind(error_kind: str) -> bool:
    return error_kind in _TRANSIENT_KINDS


def evaluate_batch_pause(*, success_count: int, failure_kinds: list[str]) -> tuple[bool, str, str]:
    """Decide whether the compile worker should pause after a batch."""
    if success_count > 0 or not failure_kinds:
        return False, "", ""

    pause_kinds = [kind for kind in failure_kinds if kind in _PAUSE_KINDS]
    if pause_kinds:
        primary = pause_kinds[0]
        return True, sanitize_display_message("API credentials or billing rejected further compiles"), primary

    if len(failure_kinds) >= 3 and all(kind in _TRANSIENT_KINDS for kind in failure_kinds):
        primary = failure_kinds[0]
        return True, sanitize_display_message("Repeated rate limit or overload errors paused compilation"), primary

    if len(failure_kinds) >= 5:
        primary = failure_kinds[0]
        return True, sanitize_display_message("Too many compile failures in one batch"), primary

    return False, "", ""
