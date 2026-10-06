"""Data contracts and models for Long Session Epoch Splitter and Milestone Archiver."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EpochSplitUrgency(StrEnum):
    """Urgency level indicating whether a session should be split into a new epoch."""

    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"
    SPLIT_IMMEDIATELY = "split_immediately"


@dataclass(frozen=True)
class SessionSaturationProbeReport:
    """Proactive probe diagnostic for message count and context saturation."""

    message_count: int
    estimated_tokens: int
    max_context_window: int
    saturation_ratio: float
    urgency: EpochSplitUrgency
    should_auto_fork: bool
    diagnostic_reason: str


@dataclass(frozen=True)
class MilestoneArtifactRef:
    """Active file or artifact reference retained across session epochs."""

    path: str
    version: str
    summary: str


@dataclass(frozen=True)
class MilestoneCheckpointPayload:
    """Structured milestone snapshot capturing completed goals and pending work."""

    session_id: str
    epoch_index: int
    parent_session_id: str | None
    completed_goals: tuple[str, ...]
    pending_tasks: tuple[str, ...]
    active_artifacts: tuple[MilestoneArtifactRef, ...]
    key_decisions: tuple[str, ...]
    created_at_utc: str


@dataclass(frozen=True)
class ForkedEpochSessionDescriptor:
    """Descriptor for the smoothly forked next-epoch session with inherited state."""

    next_session_id: str
    parent_session_id: str
    epoch_index: int
    checkpoint: MilestoneCheckpointPayload
    hydrated_preamble: str
