"""Durable Agent Harness core types and data contracts.

[INPUT]
- None (Standard library primitives and typed structures)

[OUTPUT]
- EffectType: Enumeration of external side-effect operations (MODEL_CALL, TOOL_EXECUTION, CONTEXT_COMPACT, BRANCH_NAVIGATE).
- IntentStatus: Status of an IntentRecord (PENDING, COMPLETED, INTERRUPTED, ABORTED).
- ReplaySafetyLevel: Safety level classification (SAFE, UNSAFE, IDEMPOTENT).
- IntentRecord: Pre-allocated intent log entry stored prior to side-effect execution.
- TreeEntry: Append-only immutable dialogue and message node in the conversation DAG.
- LaneState: Swimlane pointer state maintaining current leaf, status, and attempt counts.
- OperationLogEntry: Ephemeral operational event log decoupled from LLM context.
- GlobalFactRecord: Session-level persistent facts and configuration.
- UsageRecord: Monotonic immutable token and cost persistence record.
- ReplayDecision: Replay safety verdict and execution fallback action.

[POS]
Core data structures for the durable stateful agent runtime and intent ledger.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class EffectType(str, Enum):
    """Types of operations producing external side-effects."""

    MODEL_CALL = "model_call"
    TOOL_EXECUTION = "tool_execution"
    CONTEXT_COMPACT = "context_compact"
    BRANCH_NAVIGATE = "branch_navigate"


class IntentStatus(str, Enum):
    """Lifecycle state of an Intent Record."""

    PENDING = "pending"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    ABORTED = "aborted"


class ReplaySafetyLevel(str, Enum):
    """Safety classification for replaying uncompleted operations upon crash recovery."""

    SAFE = "safe"  # Read-only operations, safe to re-execute unconditionally
    UNSAFE = "unsafe"  # Side-effect mutation operations, must inject synthetic interrupted fallback
    IDEMPOTENT = "idempotent"  # Operations with explicit idempotent key, safe to re-evaluate


@dataclass(slots=True)
class IntentRecord:
    """Pre-allocated intent log entry written prior to executing any external side-effect."""

    intent_id: str
    session_id: str
    lane_id: str
    effect_type: EffectType
    source_leaf_id: str | None
    provisioned_result_id: str
    payload: dict[str, Any]
    status: IntentStatus = IntentStatus.PENDING
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    completed_at_ms: int | None = None
    error_message: str | None = None


@dataclass(slots=True)
class TreeEntry:
    """Append-only immutable node in the session dialogue tree DAG."""

    entry_id: str
    session_id: str
    parent_id: str | None
    entry_type: str  # message, system_prompt, compact_summary, tool_call, tool_result
    content: str | dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    sequence: int = 0
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    checksum_sha256: str | None = None


@dataclass(slots=True)
class LaneState:
    """State pointer and execution progress of a parallel workflow swimlane."""

    lane_id: str
    session_id: str
    current_leaf_id: str | None
    status: str = "idle"  # idle, running, interrupted, completed, aborted
    attempt_count: int = 0
    parent_lane_id: str | None = None
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    updated_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass(slots=True)
class OperationLogEntry:
    """Ephemeral operation log entry recording scheduler intents and transient step logs."""

    op_id: str
    session_id: str
    lane_id: str
    op_type: str  # step_attempt, tool_started, queue_enqueued, steering_applied
    payload: dict[str, Any]
    sequence: int = 0
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass(slots=True)
class GlobalFactRecord:
    """Session-level global facts, tags, and configuration."""

    fact_key: str
    session_id: str
    fact_value: Any
    updated_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass(slots=True)
class UsageRecord:
    """Monotonic immutable token and financial cost persistence record across crashes."""

    usage_id: str
    session_id: str
    lane_id: str
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: int = 0
    estimated_cost_usd: float = 0.0
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass(slots=True)
class ReplayDecision:
    """Replay safety verdict and execution fallback action."""

    can_reexecute: bool
    safety_level: ReplaySafetyLevel
    synthetic_result_payload: dict[str, Any] | None = None
    reason: str = ""


def generate_provisioned_id(prefix: str = "res") -> str:
    """Generate a high-entropy unique provisioned entry ID."""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"
