# -*- coding: utf-8 -*-
"""Data types for Subagent Live Transcript, Persistent Delegation, and Smart Approvals.

Aligned with Hermes v0.19 delegation transparency, persistent ledger, and MoA reasoning.

[INPUT]
- enum
- typing
- pydantic

[OUTPUT]
- JsonPrimitive
- JsonValue
- TranscriptEventKind
- TaskDelegationStatus
- ReasoningEffortLevel
- ApprovalDecision
- SubagentTranscriptEvent
- DelegationTaskRecord
- SmartApprovalRequest
- SmartApprovalResolution

[POS]
Data types for Subagent Live Transcript, Persistent Delegation, and Smart Approvals.
"""

from enum import Enum
from typing import Dict, List, Optional, Union
from pydantic import BaseModel, Field

# Concrete JSON-safe primitive types to strictly avoid `Any`
JsonPrimitive = Union[str, int, float, bool, None]
JsonValue = Union[
    JsonPrimitive,
    List[JsonPrimitive],
    Dict[str, JsonPrimitive],
    List[Dict[str, JsonPrimitive]],
]


class TranscriptEventKind(str, Enum):
    """Lifecycle and telemetry kinds of subagent live transcript events."""

    THOUGHT = "thought"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    STATE_CHANGE = "state_change"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"
    DENIED_FEEDBACK = "denied_feedback"
    SUMMARY = "summary"
    ERROR = "error"


class TaskDelegationStatus(str, Enum):
    """Execution status of background delegated subagent tasks."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReasoningEffortLevel(str, Enum):
    """Dynamic reasoning effort levels for Mixture of Agents (MoA)."""

    LOW = "low"
    MEDIUM = "medium"
    MAX = "max"
    ULTRA = "ultra"


class ApprovalDecision(str, Enum):
    """Smart approval adjudication outcome."""

    APPROVED = "approved"
    DENIED = "denied"


class SubagentTranscriptEvent(BaseModel):
    """Human-readable live transcript event emitted by a subagent."""

    task_id: str
    subagent_id: str
    seq: int
    timestamp: float
    kind: TranscriptEventKind
    human_readable: str
    payload: Dict[str, JsonValue] = Field(default_factory=dict)


class DelegationTaskRecord(BaseModel):
    """Persistent snapshot ledger record for delegated subagent tasks."""

    task_id: str
    session_id: str
    subagent_id: str
    role: str
    prompt: str
    reasoning_effort: ReasoningEffortLevel = ReasoningEffortLevel.MEDIUM
    status: TaskDelegationStatus = TaskDelegationStatus.PENDING
    created_at: float
    updated_at: float
    finished_at: Optional[float] = None
    checkpoint_step: int = 0
    event_count: int = 0
    artifacts: List[Dict[str, str]] = Field(default_factory=list)
    summary: Optional[str] = None
    error_message: Optional[str] = None


class SmartApprovalRequest(BaseModel):
    """Single-command bounded approval request."""

    approval_id: str
    task_id: str
    subagent_id: str
    command: str
    command_hash: str
    risk_score: float
    risk_reasons: List[str] = Field(default_factory=list)
    created_at: float


class SmartApprovalResolution(BaseModel):
    """Resolution of a Smart Approval request with optional /deny feedback."""

    approval_id: str
    decision: ApprovalDecision
    deny_reason: Optional[str] = None
    remediation_prompt: Optional[str] = None
    resolved_at: float
