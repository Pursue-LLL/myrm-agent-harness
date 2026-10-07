"""Types and models for graceful interruption.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- InterruptionSignalKind: Categorical kind of turn interruption signal.
- InterruptedArtifactSnapshot: A partial artifact or intermediate code piece flushed safely at interruption.
- GracefulInterruptionReport: Full post-interruption diagnostic and state report.
- SeamlessStitchedPromptBlock: Context prompt block stitched together to resume next turn smoothly.

[POS]
Types and models for graceful interruption.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class InterruptionSignalKind(StrEnum):
    """Categorical kind of turn interruption signal."""

    GRACEFUL_PREEMPTION = "graceful_preemption"
    USER_MANUAL_STOP = "user_manual_stop"
    EMERGENCY_ABORT = "emergency_abort"


@dataclass(frozen=True, slots=True)
class InterruptedArtifactSnapshot:
    """A partial artifact or intermediate code piece flushed safely at interruption."""

    artifact_id: str
    name: str
    artifact_type: str
    content_snippet: str
    bytes_length: int
    is_partially_flushed: bool = True
    meta: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GracefulInterruptionReport:
    """Full post-interruption diagnostic and state report."""

    session_id: str
    turn_index: int
    step_index_interrupted: int
    total_planned_steps: int
    signal_kind: InterruptionSignalKind
    preempting_user_message: str | None
    preserved_artifacts: list[InterruptedArtifactSnapshot]
    executed_tool_summaries: list[str]
    timestamp_iso: str


@dataclass(frozen=True, slots=True)
class SeamlessStitchedPromptBlock:
    """Context prompt block stitched together to resume next turn smoothly."""

    rendered_context_xml: str
    summary_digest: str
