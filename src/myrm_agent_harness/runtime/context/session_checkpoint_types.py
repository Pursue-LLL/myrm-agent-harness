"""Domain models and data contracts for Session State Checkpoint and Atomic Resume.

Defines Step-Level Checkpoint snapshots, pending tool call state tracking,
workspace integrity hashing, and idempotent resumption decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class CheckpointStepStatus(StrEnum):
    """Lifecycle status of an execution step checkpoint."""

    INITIALIZED = "initialized"
    STEP_STARTED = "step_started"
    TOOL_INVOKING = "tool_invoking"
    TOOL_COMPLETED = "tool_completed"
    STEP_COMMITTED = "step_committed"
    INTERRUPTED = "interrupted"


class ToolActionRecoveryKind(StrEnum):
    """Action recommendation for an interrupted tool invocation."""

    SKIP_AND_REUSE = "skip_and_reuse"
    RE_EXECUTE = "re_execute"
    FAIL_AND_ALERT = "fail_and_alert"


@dataclass(frozen=True, slots=True)
class ToolExecutionSnapshot:
    """Snapshot of a tool invocation before/after execution."""

    tool_name: str
    call_id: str
    input_args: dict[str, str] = field(default_factory=dict)
    is_idempotent: bool = False
    output_preview: str | None = None
    executed_at: float = 0.0


@dataclass(frozen=True, slots=True)
class SessionStepCheckpoint:
    """Atomic snapshot capturing state at a discrete step boundary."""

    checkpoint_id: str
    session_id: str
    step_index: int
    status: CheckpointStepStatus
    workspace_fingerprint: str
    messages_count: int
    pending_tool_call: ToolExecutionSnapshot | None = None
    timestamp: float = 0.0
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AtomicResumeDecision:
    """Directive determining whether and how to resume an interrupted session."""

    can_resume: bool
    resume_step_index: int
    recommended_action: ToolActionRecoveryKind
    prompt_instructions: str
    divergence_detected: bool = False
    last_checkpoint_id: str | None = None


@dataclass(frozen=True, slots=True)
class SessionCheckpointConfig:
    """Operational settings controlling checkpoint persistence and retention."""

    storage_dir: str | None = None
    auto_save_step: bool = True
    max_checkpoints_per_session: int = 50
