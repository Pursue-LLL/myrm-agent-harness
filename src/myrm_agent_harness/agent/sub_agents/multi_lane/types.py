"""Types and models for Pi Harness v2 multi-lane parallel execution.

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- PrimitiveValue
- MetadataDict
- LaneState
- OpStatus
- TreeNode
- LaneOperation
- LaneInfo
- MultiLaneSessionSnapshot
- MultiLaneError
- LaneConcurrencyConflictError

[POS]
Types and models for Pi Harness v2 multi-lane parallel execution.

"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum

PrimitiveValue = str | int | float | bool | None
MetadataDict = dict[str, PrimitiveValue]


class LaneState(StrEnum):
    """Execution state of a lane within a session."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    CLOSED = "closed"


class OpStatus(StrEnum):
    """Lifecycle status of an operation on a lane."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class TreeNode:
    """A node in the append-only shared tree for a session."""

    node_id: str
    parent_id: str | None
    lane_id: str
    node_type: str
    content: str
    created_at: float = field(default_factory=time.time)
    metadata: MetadataDict = field(default_factory=dict)


@dataclass
class LaneOperation:
    """An operation scheduled or executed on a lane."""

    op_id: str
    lane_id: str
    name: str
    payload: MetadataDict = field(default_factory=dict)
    status: OpStatus = OpStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    error_message: str | None = None
    result_node_id: str | None = None


@dataclass
class LaneInfo:
    """Metadata and state of a single lane."""

    lane_id: str
    display_name: str
    state: LaneState = LaneState.IDLE
    current_leaf_id: str = "root"
    active_op_id: str | None = None
    total_ops: int = 0
    created_at: float = field(default_factory=time.time)


@dataclass
class MultiLaneSessionSnapshot:
    """Read-only snapshot of all lanes and tree topology within a session."""

    session_id: str
    lanes: dict[str, LaneInfo]
    total_nodes: int
    active_lanes_count: int
    recent_op_logs: list[LaneOperation]


class MultiLaneError(Exception):
    """Base exception for multi-lane execution model."""


class LaneConcurrencyConflictError(MultiLaneError):
    """Raised when an operation is dispatched while another is open on the same lane."""


class LaneNotFoundError(MultiLaneError):
    """Raised when the specified lane is not found."""


class NodeNotFoundError(MultiLaneError):
    """Raised when a tree node parent is not found."""


class OperationNotFoundError(MultiLaneError):
    """Raised when an operation cannot be found in the lane op log."""
