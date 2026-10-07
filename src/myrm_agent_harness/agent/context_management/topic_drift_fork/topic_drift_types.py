"""Data contracts and type definitions for topic drift demarcation and auto-renamed session forking.

Detects milestone completion and semantic topic shifts in prolonged sessions,
offering intelligent non-intrusive forking with auto-renaming to prevent massive context bloat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DriftSignalKind(str, Enum):
    """Signals indicating a topic transition or milestone closure."""

    MILESTONE_COMPLETED = "milestone_completed"
    SEMANTIC_SHIFT = "semantic_shift"
    PROLONGED_SESSION = "prolonged_session"
    EXPLICIT_TOPIC_CHANGE = "explicit_topic_change"


@dataclass(frozen=True)
class TopicDriftEvaluation:
    """Diagnostic outcome of topic drift detection across dialogue turns."""

    session_id: str
    is_drift_detected: bool
    confidence: float
    detected_signals: list[DriftSignalKind]
    previous_topic: str
    new_detected_topic: str
    current_tokens: int
    turn_count: int
    reason: str


@dataclass(frozen=True)
class SessionForkSuggestion:
    """Actionable recommendation presented to users to fork into a fresh clean session."""

    old_session_id: str
    suggested_archived_title: str
    suggested_new_title: str
    carryover_summary: str
    estimated_tokens_cleared: int
    confidence: float
    user_banner_message: str


@dataclass(frozen=True)
class ForkExecutionResult:
    """Result of performing a clean session fork with auto-renaming."""

    fork_id: str
    archived_session_id: str
    archived_title: str
    new_session_id: str
    new_title: str
    carryover_summary_injected: bool
    tokens_relieved: int
    attention_focus_gain_ratio: float
