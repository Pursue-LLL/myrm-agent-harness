"""Compile failure classification and retry/pause policy.

[INPUT]
- toolkits.llms.errors.classifier::classify_error, ErrorKind (POS: LLM error taxonomy SSOT)
- .sanitize::sanitize_display_message (POS: user-safe compile error display)
- .types::FailureResolution (POS: compile failure policy result)

[OUTPUT]
- resolve_llm_failure: the error kind of an LLM failure and the backoff a queued retry waits
- resolve_embed_failure: the embed window pause reason and its error kind
- resolve_blocked_publish: the classification of an article the publish content scan refused
- evaluate_batch_pause: batch-level compile circuit pause decision
- TRANSIENT_ERROR_KINDS: the error kinds a queued retry can recover from, shared with the queue's retry selection
- is_transient_error_kind: transient retry eligibility filter
- EMBED_WINDOW_VIOLATION: embed input window error kind for compile circuit + UI

[POS]
Wiki compile failure policy. Classifies LLM failures and embed window violations, and decides retry backoff vs circuit pause.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.llms.errors.classifier import ErrorKind, classify_error
from myrm_agent_harness.toolkits.retriever.embedding.window_policy import EmbedInputTooLargeError

from .sanitize import sanitize_display_message
from .types import FailureResolution

IO_MISSING = "io_missing"
EMBED_WINDOW_VIOLATION = "embed_window_violation"

TRANSIENT_ERROR_KINDS: frozenset[str] = frozenset(
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

_TRANSIENT_BACKOFF_SECONDS: dict[str, int] = {
    ErrorKind.RATE_LIMIT.value: 120,
    ErrorKind.OVERLOADED.value: 60,
    ErrorKind.TIMEOUT.value: 30,
}


def resolve_embed_failure(exc: EmbedInputTooLargeError) -> tuple[str, str]:
    """Map an embed window violation to compile pause reason and error kind."""
    model_label = exc.model or "embedding model"
    scope = f" for '{exc.parent_key}'" if exc.parent_key else ""
    reason = sanitize_display_message(
        f"Embedding input {exc.token_count} tokens exceeds {model_label} limit "
        f"{exc.limit}{scope}. Switch to a larger-window embedding model, then resume."
    )
    return reason, EMBED_WINDOW_VIOLATION


def resolve_blocked_publish() -> FailureResolution:
    """Classify an article the publish content scan refused: the same text is refused again until its sources change."""
    return FailureResolution(error_kind=ErrorKind.SAFETY_BLOCK.value)


def resolve_llm_failure(exc: Exception) -> FailureResolution:
    """Map an LLM exception to the error kind its queue row is failed with and the backoff a retry waits."""
    error_kind = classify_error(exc).value
    backoff = _TRANSIENT_BACKOFF_SECONDS.get(error_kind, 0)
    return FailureResolution(error_kind=error_kind, retry_after_seconds=backoff)


def is_transient_error_kind(error_kind: str) -> bool:
    return error_kind in TRANSIENT_ERROR_KINDS


def evaluate_batch_pause(*, success_count: int, failure_kinds: list[str]) -> tuple[bool, str, str]:
    """Decide whether the compile worker should pause after a batch."""
    if success_count > 0 or not failure_kinds:
        return False, "", ""

    pause_kinds = [kind for kind in failure_kinds if kind in _PAUSE_KINDS]
    if pause_kinds:
        primary = pause_kinds[0]
        return True, sanitize_display_message("API credentials or billing rejected further compiles"), primary

    if len(failure_kinds) >= 3 and all(kind in TRANSIENT_ERROR_KINDS for kind in failure_kinds):
        primary = failure_kinds[0]
        return True, sanitize_display_message("Repeated rate limit or overload errors paused compilation"), primary

    if len(failure_kinds) >= 5:
        primary = failure_kinds[0]
        return True, sanitize_display_message("Too many compile failures in one batch"), primary

    return False, "", ""
