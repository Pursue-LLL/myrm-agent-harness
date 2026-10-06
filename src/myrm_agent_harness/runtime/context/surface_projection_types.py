"""Type definitions for Immutable Event Log SSOT and Surface Projection Engine.

Reference: DeepSeek Harness (@deepseek-ai/dsh) SessionSurface & arXiv:2608.24569.
Strict 0 Any, immutable frozen dataclasses for deterministic context derivation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class SessionEventType(StrEnum):
    """Enumeration of event types recorded in the immutable event log."""

    # Operational & telemetry events (non-message producing)
    TURN_START = "turn/start"
    STEP_START = "step/start"
    ASSISTANT_CHUNK = "assistant/chunk"
    TOOL_CALL = "tool/call"
    HEARTBEAT = "system/heartbeat"

    # Message-producing authoritative events
    USER_MESSAGE = "user/message"
    ASSISTANT_MESSAGE = "assistant/message"
    TOOL_RESULT = "tool/result"

    # Context transformation operations
    SURFACE_REPLACE = "surface/replace"


class MessageRole(StrEnum):
    """Role associated with a projected model message."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class SurfaceOpType(StrEnum):
    """Operation type for surface folding and compaction."""

    APPEND = "append"
    REPLACE = "replace"


@dataclass(frozen=True)
class SessionEvent:
    """Immutable event stored in the event log (SSOT)."""

    seq: int
    event_type: SessionEventType
    timestamp: float
    payload: Mapping[str, str | int | float | bool | tuple[str, ...]]
    event_id: str = ""


@dataclass(frozen=True)
class ProjectedMessage:
    """Immutable model-visible message derived from surface nodes."""

    role: MessageRole
    content: str
    tool_call_id: str | None = None
    name: str | None = None
    reasoning_content: str | None = None
    tool_calls: tuple[str, ...] = ()


@dataclass(frozen=True)
class SurfaceNode:
    """Single node in the projected surface sequence."""

    node_id: str
    source_event_seq: int
    message: ProjectedMessage
    is_summary: bool = False
    is_truncated: bool = False
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class SurfaceOp:
    """Operation applied during surface folding (e.g., compaction or tool pruning)."""

    op_type: SurfaceOpType
    start_index: int
    end_index: int
    replacement_nodes: tuple[SurfaceNode, ...]
    reason: str


@dataclass(frozen=True)
class HandoffConstraints:
    """Four core constraint dimensions required by arXiv:2608.24569 to prevent constraint weakening."""

    security_boundaries: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    required_artifacts: tuple[str, ...] = ()
    prohibited_actions: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        """Check whether any constraints are declared."""
        return not (
            self.security_boundaries
            or self.permissions
            or self.required_artifacts
            or self.prohibited_actions
        )


@dataclass(frozen=True)
class SurfaceProjectionAudit:
    """Audit report for surface projection and folding verification."""

    total_events: int
    authoritative_events_count: int
    applied_ops_count: int
    final_node_count: int
    has_preserved_constraints: bool
    audit_trail: tuple[str, ...]
