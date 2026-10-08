# [INPUT]: ThreadPageRequest, SortKeyKind, FallbackStatus
# [OUTPUT]: SortKeyFallbackGuard, GuardValidationResult
# [POS]: agent/context_management/native_thread_history/sort_key_fallback_guard.py

"""Sort key validation and graceful fallback guard for thread history retrieval.

[INPUT]
- agent.context_management.native_thread_history.thread_history_types::FallbackStatus, SortKeyKind,
  ThreadPageRequest (POS: Strongly typed contracts for large native thread history and sort key fallback.)

[OUTPUT]
- GuardValidationResult: Validation and resolution result produced by SortKeyFallbackGuard.
- SortKeyFallbackGuard: Guard preventing unhandled storage errors when unsupported sort keys are requested.

[POS]
Sort key validation and graceful fallback guard for thread history retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .thread_history_types import FallbackStatus, SortKeyKind, ThreadPageRequest

_KNOWN_SORT_KEYS: Final[set[str]] = {
    SortKeyKind.SECTION_POSITION.value,
    SortKeyKind.SEQUENCE.value,
    SortKeyKind.CREATED_AT.value,
}


@dataclass(frozen=True)
class GuardValidationResult:
    """Validation and resolution result produced by SortKeyFallbackGuard."""

    is_valid: bool
    effective_sort_key: str | None
    fallback_status: FallbackStatus
    fallback_applied: bool
    fallback_reason: str | None


class SortKeyFallbackGuard:
    """Guard preventing unhandled storage errors when unsupported sort keys are requested."""

    def __init__(self, supported_keys: set[str] | None = None) -> None:
        """Initialize guard with storage-supported sort key capability set."""
        self._supported_keys: set[str] = (
            set(supported_keys) if supported_keys is not None else set(_KNOWN_SORT_KEYS)
        )

    @property
    def supported_keys(self) -> frozenset[str]:
        """Return the immutable set of supported sort keys."""
        return frozenset(self._supported_keys)

    def evaluate_request(self, request: ThreadPageRequest) -> GuardValidationResult:
        """Evaluate request against supported sort keys and resolve fallback path.

        If the sort key is not supported by the underlying storage:
        - If allow_natural_fallback is requested, fallback to 'sequence'.
        - Otherwise, gracefully fallback to an empty page without crashing.
        """
        requested = request.sort_key.strip().lower()

        if requested in self._supported_keys:
            return GuardValidationResult(
                is_valid=True,
                effective_sort_key=requested,
                fallback_status=FallbackStatus.NORMAL,
                fallback_applied=False,
                fallback_reason=None,
            )

        if request.allow_natural_fallback:
            natural_key = SortKeyKind.SEQUENCE.value
            return GuardValidationResult(
                is_valid=True,
                effective_sort_key=natural_key,
                fallback_status=FallbackStatus.FALLBACK_NATURAL_KEY,
                fallback_applied=True,
                fallback_reason=(
                    f"Requested sort key '{request.sort_key}' is unsupported by the storage backend; "
                    f"gracefully fallen back to natural key '{natural_key}'."
                ),
            )

        return GuardValidationResult(
            is_valid=False,
            effective_sort_key=None,
            fallback_status=FallbackStatus.FALLBACK_EMPTY_PAGE,
            fallback_applied=True,
            fallback_reason=(
                f"Requested sort key '{request.sort_key}' is unsupported by the storage backend; "
                f"gracefully degraded to empty page instead of raising unhandled exception."
            ),
        )
