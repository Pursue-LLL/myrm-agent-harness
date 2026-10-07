"""Data contracts and schemas for Lean-Tail Context Lifecycle and Visualizer.

Defines three-tier segment slices (head protected, middle compacted, tail protected),
metrics, configurations, and transparent lifecycle inspection reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ContextSectionKind(StrEnum):
    """Categorized lifecycle segment in a three-tier protected context."""

    HEAD_PROTECTED = "head_protected"
    MIDDLE_COMPACTED = "middle_compacted"
    TAIL_PROTECTED = "tail_protected"


@dataclass(frozen=True, slots=True)
class ContextSectionSlice:
    """Individual segment representation with token counts and compression status."""

    kind: ContextSectionKind
    message_count: int
    original_tokens: int
    compacted_tokens: int
    is_compressed: bool
    summary_excerpt: str | None = None
    key_elements: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ContextLifecycleSectionReport:
    """Comprehensive three-tier context lifecycle audit payload."""

    session_id: str
    total_messages_before: int
    total_messages_after: int
    original_tokens: int
    compacted_tokens: int
    tokens_saved: int
    compression_ratio: float
    sections: list[ContextSectionSlice]
    retained_anchors: list[str] = field(default_factory=list)
    needs_compaction: bool = False


@dataclass(frozen=True, slots=True)
class LeanTailBoundaryConfig:
    """Configuration governing protect-first-n, protect-last-n and thresholds."""

    protect_first_n: int = 3
    protect_last_n: int = 20
    trigger_threshold_ratio: float = 0.30
    target_compression_ratio: float = 0.15
    min_middle_messages_to_compress: int = 4
