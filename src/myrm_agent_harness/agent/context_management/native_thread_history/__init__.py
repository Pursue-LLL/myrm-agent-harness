"""Native thread history preservation and sort key fallback package.

[INPUT]
-
  agent.context_management.native_thread_history.native_thread_history_preserve_suite::LargeNativeThreadHistoryPreserveSuite
  (POS: Suite implementing large native thread history preservation with sort key fallback guard.)
- agent.context_management.native_thread_history.sort_key_fallback_guard::GuardValidationResult,
  SortKeyFallbackGuard (POS: Sort key validation and graceful fallback guard for thread history retrieval.)
- agent.context_management.native_thread_history.thread_history_types::FallbackStatus, SortKeyKind,
  ThreadEntry, ThreadHistoryPage, ThreadPageRequest (POS: Strongly typed contracts for large native thread
  history and sort key fallback.)

[OUTPUT]
- Re-exports: FallbackStatus, GuardValidationResult, LargeNativeThreadHistoryPreserveSuite,
  SortKeyFallbackGuard, SortKeyKind, ThreadEntry, ThreadHistoryPage, ThreadPageRequest

[POS]
Native thread history preservation and sort key fallback package.
"""

from __future__ import annotations

from .native_thread_history_preserve_suite import LargeNativeThreadHistoryPreserveSuite
from .sort_key_fallback_guard import GuardValidationResult, SortKeyFallbackGuard
from .thread_history_types import (
    FallbackStatus,
    SortKeyKind,
    ThreadEntry,
    ThreadHistoryPage,
    ThreadPageRequest,
)

__all__ = [
    "FallbackStatus",
    "GuardValidationResult",
    "LargeNativeThreadHistoryPreserveSuite",
    "SortKeyFallbackGuard",
    "SortKeyKind",
    "ThreadEntry",
    "ThreadHistoryPage",
    "ThreadPageRequest",
]
