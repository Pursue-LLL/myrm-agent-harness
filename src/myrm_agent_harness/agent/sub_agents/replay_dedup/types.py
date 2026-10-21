"""Core types for Multi-Agent Tool Replay History Deduplication & Subagent Status Harmonization (Item 57).

[INPUT]
- Raw tool replay items and subagent status transitions.

[OUTPUT]
- Strongly-typed models for consecutive tool call batching, token compact metrics,
  and monotonic status machine transitions.

[POS]
- Framework-level types underpinning replay deduplication and anti-deadlock harmonization.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field


class ToolReplayStatusEnum(enum.StrEnum):
    """Execution status of a tool invocation or subagent lifecycle."""

    IDLE = "idle"
    RUNNING = "running"
    PENDING_APPROVAL = "pending_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT_TERMINATED = "timeout_terminated"


class ToolReplayKindEnum(enum.StrEnum):
    """Classification of tool execution semantics."""

    READ_ONLY = "read_only"
    MUTATING = "mutating"
    SYSTEM = "system"


@dataclass(frozen=True)
class ToolReplayItem:
    """Single atomic tool invocation entry in replay history."""

    call_id: str
    tool_name: str
    kind: ToolReplayKindEnum
    args: Mapping[str, str | int | float | bool]
    result_summary: str
    status: ToolReplayStatusEnum
    start_time: float
    end_time: float
    estimated_tokens: int
    subagent_id: str


@dataclass(frozen=True)
class MergedReplayBatch:
    """Aggregated batch representing consecutive idempotent read-only tool calls."""

    batch_id: str
    tool_name: str
    merged_count: int
    item_ids: Sequence[str]
    aggregated_args_summary: str
    aggregated_result_summary: str
    original_tokens: int
    compact_tokens: int
    tokens_saved: int
    start_time: float
    end_time: float
    final_status: ToolReplayStatusEnum
    subagent_id: str


@dataclass(frozen=True)
class ReplayDeduplicationResult:
    """Summary of replay history deduplication and token optimization."""

    session_id: str
    original_items_count: int
    deduplicated_items_count: int
    total_original_tokens: int
    total_compact_tokens: int
    tokens_saved: int
    reduction_ratio: float
    batches: Sequence[MergedReplayBatch] = field(default_factory=tuple)
    unmerged_items: Sequence[ToolReplayItem] = field(default_factory=tuple)


@dataclass(frozen=True)
class SubagentStatusTransitionEvent:
    """Audit record capturing subagent status progression and watchdog interventions."""

    event_id: str
    subagent_id: str
    previous_status: ToolReplayStatusEnum
    new_status: ToolReplayStatusEnum
    timestamp: float
    reason: str
    is_deadlock_prevented: bool
