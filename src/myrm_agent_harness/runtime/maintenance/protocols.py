"""Maintenance scheduling protocols and data types.

Defines the contract between Harness (task submitter), Server (load sensor),
and Control Plane (scheduler). All heavy maintenance tasks (Evolution, context
compaction, storage cleanup) must acquire a CapacityTicket before execution.

[INPUT]
- (none)

[OUTPUT]
- SystemLoadLevel: System load classification, ordered by resource availabil...
- MaintenanceTaskType: Types of maintenance tasks, ordered by resource intensity.
- SystemLoadSnapshot: Point-in-time system resource snapshot from a LoadSensor.
- AgentHealthScore: Composite health score for an Agent's data quality.
- CapacityTicket: Permission token granted by the scheduler to run a mainte...

[POS]
Maintenance scheduling protocols and data types.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import IntEnum, auto
from typing import Protocol, runtime_checkable


class SystemLoadLevel(IntEnum):
    """System load classification, ordered by resource availability."""

    IDLE = 0
    NORMAL = 1
    BUSY = 2
    OVERLOADED = 3


class MaintenanceTaskType(IntEnum):
    """Types of maintenance tasks, ordered by resource intensity."""

    STORAGE_CLEANUP = auto()
    CONTEXT_COMPACTION = auto()
    WIKI_MAINTENANCE = auto()
    EVOLUTION = auto()
    SKILL_CONSOLIDATION = auto()
    EMBEDDING_REBUILD = auto()
    MEMORY_MAINTENANCE = auto()


@dataclass(frozen=True, slots=True)
class SystemLoadSnapshot:
    """Point-in-time system resource snapshot from a LoadSensor."""

    level: SystemLoadLevel
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    api_quota_remaining_pct: float = 100.0
    detail: str = ""
    timestamp: float = field(default_factory=time.monotonic)


@dataclass(frozen=True, slots=True)
class AgentHealthScore:
    """Composite health score for an Agent's data quality.

    Score range: 0-100. Lower scores indicate more urgent maintenance needs.
    Only agents below the threshold should trigger background maintenance.
    """

    score: int
    evolution_backlog: int = 0
    context_fragmentation_pct: float = 0.0
    storage_usage_pct: float = 0.0

    def needs_maintenance(self, threshold: int = 70) -> bool:
        return self.score < threshold


@dataclass(frozen=True, slots=True)
class CapacityTicket:
    """Permission token granted by the scheduler to run a maintenance task.

    Holders must call `release()` on the scheduler when done.
    """

    ticket_id: str
    task_type: MaintenanceTaskType
    granted_at: float = field(default_factory=time.monotonic)

    @property
    def age_seconds(self) -> float:
        return time.monotonic() - self.granted_at


@dataclass(frozen=True, slots=True)
class CapacityDenial:
    """Returned when the scheduler refuses a maintenance request."""

    reason: str
    retry_after_seconds: float = 30.0
    load_snapshot: SystemLoadSnapshot | None = None


@runtime_checkable
class LoadSensor(Protocol):
    """Protocol for system load detection.

    Implementations differ by deployment mode:
    - DeviceLoadSensor: Local/Tauri — reads CPU/memory via psutil
    - ClusterLoadSensor: SaaS — reads API rate-limit headroom and queue depth
    """

    def read(self) -> SystemLoadSnapshot: ...


@runtime_checkable
class MaintenanceScheduler(Protocol):
    """Protocol for the global maintenance scheduler.

    Harness-layer components request capacity through this interface.
    The scheduler decides based on current load and health scores.
    """

    async def request_capacity(
        self,
        task_type: MaintenanceTaskType,
        health_score: AgentHealthScore | None = None,
    ) -> CapacityTicket | CapacityDenial:
        """Request permission to run a maintenance task.

        Returns CapacityTicket if approved, CapacityDenial if system is busy.
        """
        ...

    async def release_capacity(self, ticket: CapacityTicket) -> None:
        """Release a previously granted capacity ticket."""
        ...

    def is_idle(self) -> bool:
        """Quick check: is the system currently idle enough for maintenance?"""
        ...
