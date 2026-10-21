"""Data types and schemas for Hierarchical Context Timeout Tree and Cancel Propagation Suite.

Defines timeout levels, cascade cancellation signals, task execution handles,
and zombie task audit reports for deterministic agent lifecycle control.

[INPUT]
- __future__
- time
- collections
- dataclasses
- enum

[OUTPUT]
- TimeoutLevel
- CancelReason
- CascadeCancelSignal
- CancelHookCallback
- TaskExecutionHandle
- ZombieReaperReport

[POS]
Data types and schemas for Hierarchical Context Timeout Tree and Cancel Propagation Suite.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import StrEnum


class TimeoutLevel(StrEnum):
    """Architectural layer within the hierarchical timeout ladder."""

    GATEWAY = "gateway"  # Layer 1: Ingress API Gateway level (e.g. 60s)
    AGENT_CONTEXT = "agent_context"  # Layer 2: Main Agent reasoning loop (e.g. Gateway - 5s = 55s)
    LLM_CALL = "llm_call"  # Layer 3: Single model completion round (e.g. <= 30s)
    TOOL_EXEC = "tool_exec"  # Layer 4: Tool execution (e.g. 5s for I/O, 30s for Sandbox)


class CancelReason(StrEnum):
    """Root cause triggering a cascade cancellation."""

    USER_DISCONNECT = "user_disconnect"  # Client disconnected, closed tab, or clicked stop
    UPSTREAM_TIMEOUT = "upstream_timeout"  # Parent node deadline expired
    ENGINE_SHUTDOWN = "engine_shutdown"  # Host process or worker terminating
    PARENT_CANCELLED = "parent_cancelled"  # Ancestor node was explicitly aborted
    EXPLICIT_ABORT = "explicit_abort"  # Programmatic cancellation requested


@dataclass(frozen=True)
class CascadeCancelSignal:
    """Cancellation message transmitted downstream through the timeout tree."""

    source_level: TimeoutLevel
    reason: CancelReason
    details: str = ""
    triggered_at: float = field(default_factory=time.time)


CancelHookCallback = Callable[[], Coroutine[object, object, None] | None]


@dataclass
class TaskExecutionHandle:
    """Tracks a scheduled task or background handle bound to a timeout tree node."""

    task_id: str
    level: TimeoutLevel
    name: str
    is_active: bool = True
    cancel_hook: CancelHookCallback | None = None
    registered_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ZombieReaperReport:
    """Summary of orphan task cleanup performed during session boundary teardown."""

    scanned_count: int
    reaped_count: int
    reaped_task_ids: tuple[str, ...]
    has_leaked_tasks: bool
    reaped_at: float = field(default_factory=time.time)
