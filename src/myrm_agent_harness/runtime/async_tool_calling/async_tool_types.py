"""Type definitions and contracts for Async Non-Blocking Tool Calling and Overlapped Inference.

Provides structured models for lightweight tool future handles, job statuses,
opt-out sync wait mechanics (SyncWaitToolOptOut), and out-of-band completion events.

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- ToolExecutionMode
- ToolJobStatus
- ToolFutureHandle
- ToolJobResult
- AsyncToolMetadata
- ToolCompletedEvent

[POS]
Type definitions and contracts for Async Non-Blocking Tool Calling and Overlapped Inference.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class ToolExecutionMode(StrEnum):
    """Execution dispatch mode for tool calls."""

    SYNC = "sync"  # Standard synchronous blocking execution
    ASYNC_FUTURE = "async_future"  # Non-blocking async execution returning lightweight handle
    SYNC_WAIT_OPTOUT = "sync_wait_optout"  # Explicit opt-out for wait/yield tools that must block


class ToolJobStatus(StrEnum):
    """Lifecycle status of a dispatched tool job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class ToolFutureHandle:
    """Lightweight future handle returned immediately when a tool is called asynchronously.

    Allows the agent to continue overlapped inference without waiting for tool completion.
    """

    task_id: str
    tool_name: str
    status: ToolJobStatus
    estimated_duration_s: float
    submitted_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, str | float]:
        """Convert handle to a JSON-safe dictionary for model context injection."""
        return {
            "task_id": self.task_id,
            "tool_name": self.tool_name,
            "status": self.status.value,
            "estimated_duration_s": self.estimated_duration_s,
            "submitted_at": self.submitted_at,
        }


@dataclass(frozen=True)
class ToolJobResult:
    """Terminal execution outcome of a tool execution."""

    task_id: str
    tool_name: str
    status: ToolJobStatus
    return_value: str = ""
    error_msg: str = ""
    duration_s: float = 0.0
    finished_at: float = field(default_factory=time.time)

    @property
    def is_success(self) -> bool:
        """True if the job completed successfully without error."""
        return self.status == ToolJobStatus.COMPLETED


@dataclass(frozen=True)
class AsyncToolMetadata:
    """Metadata and registration descriptor for tool capabilities."""

    tool_name: str
    supports_async: bool = True
    default_mode: ToolExecutionMode = ToolExecutionMode.ASYNC_FUTURE
    default_estimated_duration_s: float = 5.0
    timeout_s: float = 60.0
    is_wait_or_yield_tool: bool = False


@dataclass(frozen=True)
class ToolCompletedEvent:
    """Out-of-band notification event delivered when an asynchronous tool job completes."""

    task_id: str
    tool_name: str
    result: ToolJobResult
    event_timestamp: float = field(default_factory=time.time)
