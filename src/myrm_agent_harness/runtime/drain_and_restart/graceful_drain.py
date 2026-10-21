"""Graceful service drain coordinator for zero-downtime maintenance.

Tracks active long-horizon agent tasks and leaf tool executions, rejects
incoming root requests once drain is initiated, and waits for active
workloads to complete safely before process termination.

[OUTPUT]
- GracefulDrainCoordinator: Orchestrates task tracking and graceful drain lifecycle.

[INPUT]
- __future__
- asyncio
- contextlib
- time
- uuid
- collections

[OUTPUT]
- DrainListener
- GracefulDrainCoordinator

[POS]
Graceful service drain coordinator for zero-downtime maintenance.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager

from myrm_agent_harness.runtime.drain_and_restart.drain_types import (
    DrainNotice,
    DrainState,
    InFlightTaskInfo,
    ServiceDrainingError,
)

DrainListener = Callable[[DrainNotice], Coroutine[None, None, None]]


class GracefulDrainCoordinator:
    """Manages active task registration, drain lifecycle, and completion barriers."""

    def __init__(self, service_name: str = "default_service") -> None:
        self.service_name: str = service_name
        self._state: DrainState = "RUNNING"
        self._in_flight: dict[str, InFlightTaskInfo] = {}
        self._drain_budget: float = 45.0
        self._initiated_at: float | None = None
        self._listeners: list[DrainListener] = []

        self._lock: asyncio.Lock = asyncio.Lock()
        self._drain_done_event: asyncio.Event = asyncio.Event()
        self._drain_done_event.set()

    @property
    def state(self) -> DrainState:
        """Return current drain lifecycle state."""
        return self._state

    @property
    def in_flight_count(self) -> int:
        """Return count of currently active in-flight tasks."""
        return len(self._in_flight)

    @property
    def is_draining(self) -> bool:
        """Return True if service is draining or has completed draining."""
        return self._state in ("DRAINING", "DRAINED")

    def register_drain_listener(self, listener: DrainListener) -> None:
        """Register an async callback invoked when drain is initiated."""
        self._listeners.append(listener)

    @asynccontextmanager
    async def track_task(
        self,
        task_id: str,
        task_type: str = "agent_turn",
        *,
        is_leaf: bool = False,
    ) -> AsyncIterator[InFlightTaskInfo]:
        """Context manager to track an executing task under drain constraints."""
        async with self._lock:
            if self.is_draining and not is_leaf:
                raise ServiceDrainingError(
                    f"Service '{self.service_name}' is currently {self._state}; "
                    f"new root tasks like '{task_id}' are rejected."
                )

            task_info = InFlightTaskInfo(
                task_id=task_id,
                task_type=task_type,
                is_leaf=is_leaf,
                started_at=time.time(),
            )
            self._in_flight[task_id] = task_info
            self._drain_done_event.clear()

        try:
            yield task_info
        finally:
            async with self._lock:
                self._in_flight.pop(task_id, None)
                if not self._in_flight:
                    self._drain_done_event.set()
                    if self._state == "DRAINING":
                        self._state = "DRAINED"

    async def initiate_drain(
        self,
        reason: str,
        drain_budget_seconds: float = 45.0,
    ) -> DrainNotice:
        """Initiate graceful drain mode and notify registered listeners."""
        async with self._lock:
            self._drain_budget = max(1.0, drain_budget_seconds)
            self._initiated_at = time.time()

            if not self._in_flight:
                self._state = "DRAINED"
                self._drain_done_event.set()
            else:
                self._state = "DRAINING"
                self._drain_done_event.clear()

            notice = DrainNotice(
                notice_id=str(uuid.uuid4()),
                reason=reason,
                drain_budget_seconds=self._drain_budget,
                initiated_at=self._initiated_at,
                in_flight_count=len(self._in_flight),
            )

        # Trigger listeners outside the lock to prevent deadlocks
        for listener in self._listeners:
            with contextlib.suppress(Exception):
                await listener(notice)

        return notice

    async def cancel_drain(self) -> None:
        """Cancel drain mode and restore active service state (rollback protection)."""
        async with self._lock:
            self._state = "RUNNING"
            self._initiated_at = None
            if not self._in_flight:
                self._drain_done_event.set()

    async def wait_for_drain(self, timeout_seconds: float | None = None) -> bool:
        """Wait for active in-flight tasks to terminate within budget.

        Returns:
            bool: True if all tasks completed cleanly, False if budget expired.
        """
        budget = timeout_seconds if timeout_seconds is not None else self._drain_budget
        try:
            await asyncio.wait_for(self._drain_done_event.wait(), timeout=budget)
            async with self._lock:
                if not self._in_flight and self._state == "DRAINING":
                    self._state = "DRAINED"
            return True
        except TimeoutError:
            return False

    async def get_active_tasks_snapshot(self) -> list[InFlightTaskInfo]:
        """Return a snapshot list of currently active tasks."""
        async with self._lock:
            return list(self._in_flight.values())
