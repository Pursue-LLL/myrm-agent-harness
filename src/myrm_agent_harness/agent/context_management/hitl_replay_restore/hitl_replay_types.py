# [INPUT]: None
# [OUTPUT]: HITLApprovalState, PendingHITLDescriptor, ReplayActionKind, ReplayRestorationSummary, ToolCallReplayItem, ToolExecutionType, ToolResultReplayItem
# [POS]: agent/context_management/hitl_replay_restore/hitl_replay_types.py

"""Domain contracts for reconnect passive replay and selective HITL restoration.

[INPUT]
- None (Self-contained strongly typed domain definitions).

[OUTPUT]
- ToolExecutionType: Category distinguishing ordinary side-effect tools from HITL tools.
- ReplayActionKind: Replay handling classification (passive no-op vs pending HITL restore vs completed skip).
- HITLApprovalState: Approval status of human-in-the-loop decisions.
- ToolCallReplayItem: Replay frame representing a tool call request.
- ToolResultReplayItem: Replay frame representing a tool output or approval response.
- PendingHITLDescriptor: Restored pending human-in-the-loop registration ready for user interaction.
- ReplayRestorationSummary: Complete summary report of passive replay processing.

[POS]
Domain contracts for reconnect passive replay filtering and human-in-the-loop selective restoration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time


class ToolExecutionType(str, Enum):
    """Classification of tool execution semantics."""

    ORDINARY = "ordinary"
    HUMAN_IN_THE_LOOP = "human-in-the-loop"


class ReplayActionKind(str, Enum):
    """Categorization of tool call handling during passive replay."""

    PASSIVE_NOOP = "passive_noop"
    RESTORE_PENDING_HITL = "restore_pending_hitl"
    SKIP_COMPLETED_HITL = "skip_completed_hitl"


class HITLApprovalState(str, Enum):
    """State of a human-in-the-loop approval decision."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass(frozen=True)
class ToolCallReplayItem:
    """Historical tool call message frame in replay stream."""

    tool_call_id: str
    tool_name: str
    tool_type: ToolExecutionType = ToolExecutionType.ORDINARY
    arguments: dict[str, str] = field(default_factory=dict)
    prompt_description: str = ""
    timestamp_utc: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ToolResultReplayItem:
    """Historical tool result message frame in replay stream."""

    tool_call_id: str
    content: str
    is_error: bool = False
    timestamp_utc: float = field(default_factory=time.time)


@dataclass(frozen=True)
class PendingHITLDescriptor:
    """Restored pending human-in-the-loop registration."""

    tool_call_id: str
    tool_name: str
    arguments: dict[str, str]
    prompt_description: str
    registered_at_utc: float
    state: HITLApprovalState = HITLApprovalState.PENDING


@dataclass(frozen=True)
class ReplayRestorationSummary:
    """Structured report returned after processing passive reconnect replay."""

    session_id: str
    total_frames_processed: int
    passive_tools_skipped: int
    completed_hitl_skipped: int
    restored_pending_hitl: list[PendingHITLDescriptor]
    timestamp_utc: float
    is_awaiting_user_approval: bool
