"""Helpers for CacheTtlPruneProcessor.

[INPUT]
- infra.schemas::CacheTtlPruneConfig, ContextOffloadFailureKind
- infra.archive_reference::build_tool_result_archive_reference
- infra.tool_result_trimming::trim_tool_result_content

[OUTPUT]
- Small helper DTOs and pure message/content transformation helpers for cache TTL pruning.

[POS]
Cache TTL pruning helper layer. Keeps the processor focused on orchestration and budget decisions.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from ...infra.archive_reference import build_tool_result_archive_reference
from ...infra.schemas import CacheTtlPruneConfig, ContextOffloadFailureKind
from ...infra.tool_result_trimming import trim_tool_result_content


@dataclass(frozen=True, slots=True)
class EffectivePrunePolicy:
    """Session-adjusted pruning thresholds for one decision."""

    soft_trim_ratio: float
    hard_clear_ratio: float
    min_prunable_tokens: int
    backoff_applied: bool = False
    backoff_reasons: tuple[str, ...] = ()
    backoff_sample_count: int = 0
    backoff_bad_signal_count: int = 0
    backoff_recovery_sample_count: int = 0


@dataclass(slots=True)
class PruneStats:
    """Mutable counters for one cache-TTL pruning pass."""

    soft_trimmed: int = 0
    archived: int = 0
    offload_failed: int = 0
    original_tokens: int = 0
    offload_failure_kinds: dict[str, int] = field(default_factory=dict)
    deferred: int = 0
    deferred_reasons: dict[str, int] = field(default_factory=dict)
    archive_deferred: int = 0
    archive_deferred_reasons: dict[str, int] = field(default_factory=dict)
    archive_deferred_soft_trimmed: int = 0
    archive_deferred_soft_trimmed_reasons: dict[str, int] = field(default_factory=dict)
    archive_written: int = 0
    archive_reused: int = 0
    archive_bytes_written: int = 0
    archive_bytes_reused: int = 0

    def record_offload_failure(self, failure_kind: ContextOffloadFailureKind) -> None:
        self.offload_failed += 1
        self.offload_failure_kinds[failure_kind] = self.offload_failure_kinds.get(failure_kind, 0) + 1

    def record_deferred(self, reason: str) -> None:
        self.deferred += 1
        self.deferred_reasons[reason] = self.deferred_reasons.get(reason, 0) + 1

    def record_archive_deferred(self, reason: str) -> None:
        self.archive_deferred += 1
        self.archive_deferred_reasons[reason] = self.archive_deferred_reasons.get(reason, 0) + 1

    def record_archive_deferred_soft_trimmed(self, reason: str) -> None:
        self.archive_deferred_soft_trimmed += 1
        self.archive_deferred_soft_trimmed_reasons[reason] = (
            self.archive_deferred_soft_trimmed_reasons.get(reason, 0) + 1
        )


@dataclass(frozen=True, slots=True)
class ArchiveAttempt:
    """Result of trying to offload one prunable tool message."""

    archived: bool
    replacement_content: str = ""
    failure_kind: ContextOffloadFailureKind | None = None
    offload_reused: bool = False
    original_bytes: int = 0
    stored_bytes: int = 0


@dataclass(frozen=True, slots=True)
class ArchiveBudgetDecision:
    """Archive budget decision for a single candidate."""

    allowed: bool
    reason: str = ""


def content_to_text(content: str | Sequence[object]) -> str:
    """Convert ToolMessage content to a restorable text payload."""
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, default=str)


def find_first_human_index(messages: list[BaseMessage]) -> int | None:
    """Find index of the first HumanMessage."""
    for i, msg in enumerate(messages):
        if isinstance(msg, HumanMessage):
            return i
    return None


def find_assistant_cutoff(messages: list[BaseMessage], keep_last: int) -> int:
    """Find the index at which recent assistant turns become protected."""
    if keep_last <= 0:
        return len(messages)

    remaining = keep_last
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], AIMessage):
            remaining -= 1
            if remaining == 0:
                return i
    return 0


def soft_trim_content(content: str, config: CacheTtlPruneConfig) -> str | None:
    """Apply deterministic soft trim to tool result content."""
    trimmed = trim_tool_result_content(content, config)
    return trimmed.content if trimmed is not None else None


def build_archived_placeholder(
    *,
    tool_name: str,
    archive_path: str,
    content: str,
    original_tokens: int,
    original_chars: int,
) -> str:
    """Build a compact reference that lets the model restore archived output."""
    archive_ref = build_tool_result_archive_reference(
        tool_name=tool_name,
        archive_path=archive_path,
        content=content,
        original_tokens=original_tokens,
        original_chars=original_chars,
    )
    return archive_ref.render_for_model()


def replace_tool_content(msg: ToolMessage, content: str) -> ToolMessage:
    """Copy a LangChain ToolMessage with updated content."""
    if hasattr(msg, "model_copy"):
        copied = msg.model_copy(update={"content": content})
    else:
        copied = msg.copy(update={"content": content})
    return copied


__all__ = [
    "ArchiveAttempt",
    "ArchiveBudgetDecision",
    "EffectivePrunePolicy",
    "PruneStats",
    "build_archived_placeholder",
    "content_to_text",
    "find_assistant_cutoff",
    "find_first_human_index",
    "replace_tool_content",
    "soft_trim_content",
]
