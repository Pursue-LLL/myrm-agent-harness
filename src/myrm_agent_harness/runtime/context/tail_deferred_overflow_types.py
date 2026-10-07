"""Tail-only context append and disambiguated overflow types.

Defines immutable data models and enums for preserving provider prefix cache,
deferred writing at checkpoints, finish reason disambiguation, and single-shot
conversational recovery bounds.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class DeferredWritePriority(StrEnum):
    """Priority level for messages queued during step execution."""

    NORMAL = "normal"
    HIGH = "high"
    SYSTEM_ALERT = "system_alert"


class StopReasonVerdict(StrEnum):
    """Categorized verdict for model finish or stop reason."""

    NORMAL_STOP = "normal_stop"
    TOOL_USE = "tool_use"
    MAX_OUTPUT_TOKENS_REACHED = "max_output_tokens_reached"
    CONTEXT_WINDOW_OVERFLOW = "context_window_overflow"
    CONTENT_FILTER = "content_filter"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DeferredMessageEntry:
    """Represents a message staged during an in-flight step execution."""

    entry_id: str
    role: str
    content: str
    priority: DeferredWritePriority = DeferredWritePriority.NORMAL
    metadata: Mapping[str, str] = field(default_factory=dict)
    staged_at_ms: int = 0


@dataclass(frozen=True)
class DisambiguationMetrics:
    """Metrics used to reliably distinguish maxTokens exhaustion from window overflow."""

    actual_output_tokens: int
    max_output_tokens_budget: int
    prompt_tokens: int
    model_context_limit: int
    output_token_tolerance: int = 4


@dataclass(frozen=True)
class RecoveryVerdict:
    """Decision outcome of whether context compaction recovery is permissible."""

    can_recover: bool
    input_id: str
    recovery_attempts: int
    reason: str
