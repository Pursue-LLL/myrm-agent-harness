"""Single-writer FIFO mutation line eliminating check-then-act race conditions.

[INPUT]
- .types::LaneState, OperationLogEntry
- .protocols::DurableStorageProtocol

[OUTPUT]
- MutationAction: Enumeration of state mutation intents (STEER, FOLLOW_UP, TRY_FINISH, ABORT, ATTEMPT_START).
- MutationTask: Typed container for atomic mutation decisions.
- LaneMutationLine: Single-writer FIFO pipeline per lane.

[POS]
State machine transition serializer ensuring deterministic ordering of concurrent events.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine

from myrm_agent_harness.agent.durable.protocols import DurableStorageProtocol
from myrm_agent_harness.agent.durable.types import LaneState, OperationLogEntry


class MutationAction(str, Enum):
    """Types of state mutation actions."""

    STEER = "steer"
    FOLLOW_UP = "follow_up"
    TRY_FINISH = "try_finish"
    ABORT = "abort"
    ATTEMPT_START = "attempt_start"
    STEP_ADVANCE = "step_advance"


@dataclass(slots=True)
class MutationTask:
    """Atomic mutation request processed by the single-writer line."""

    task_id: str
    action: MutationAction
    payload: dict[str, Any]
    future: asyncio.Future[Any] = field(default_factory=lambda: asyncio.get_event_loop().create_future())
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))


class LaneMutationLine:
    """Single-writer FIFO serializer per lane guaranteeing zero-race state transitions."""

    def __init__(
        self,
        session_id: str,
        lane_id: str,
        storage: DurableStorageProtocol,
    ) -> None:
        self.session_id = session_id
        self.lane_id = lane_id
        self.storage = storage
        self._queue: asyncio.Queue[MutationTask] = asyncio.Queue()
        self._is_running = False
        self._worker_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the FIFO mutation line processor."""
        async with self._lock:
            if not self._is_running:
                self._is_running = True
                self._worker_task = asyncio.create_task(self._process_loop())

    async def stop(self) -> None:
        """Gracefully drain and stop the mutation processor."""
        async with self._lock:
            self._is_running = False
            if self._worker_task and not self._worker_task.done():
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except asyncio.CancelledError:
                    pass

    async def submit_mutation(self, action: MutationAction, payload: dict[str, Any] | None = None) -> Any:
        """Submit an atomic mutation decision and await its serialized outcome."""
        await self.start()
        task = MutationTask(
            task_id=f"mut_{uuid.uuid4().hex[:12]}",
            action=action,
            payload=payload or {},
        )
        await self._queue.put(task)
        return await task.future

    async def _process_loop(self) -> None:
        """Internal processing loop consuming mutation tasks strictly sequentially."""
        while self._is_running:
            try:
                task = await self._queue.get()
            except asyncio.CancelledError:
                break
            try:
                result = await self._execute_mutation(task)
                if not task.future.done():
                    task.future.set_result(result)
            except Exception as ex:
                if not task.future.done():
                    task.future.set_exception(ex)
            finally:
                self._queue.task_done()

    async def _execute_mutation(self, task: MutationTask) -> Any:
        """Execute the atomic transition against durable storage."""
        lane = await self.storage.get_or_create_lane(self.session_id, self.lane_id)

        # Log operational audit
        await self.storage.append_operation_log(
            OperationLogEntry(
                op_id=task.task_id,
                session_id=self.session_id,
                lane_id=self.lane_id,
                op_type=f"mutation_{task.action.value}",
                payload=task.payload,
            )
        )

        if task.action == MutationAction.STEER:
            lane.status = "running"
            await self.storage.update_lane_state(lane)
            return {"status": "steered", "steer_payload": task.payload}

        elif task.action == MutationAction.FOLLOW_UP:
            lane.status = "running"
            await self.storage.update_lane_state(lane)
            return {"status": "follow_up_accepted"}

        elif task.action == MutationAction.TRY_FINISH:
            if lane.status != "aborted":
                lane.status = "completed"
                await self.storage.update_lane_state(lane)
            return {"status": lane.status}

        elif task.action == MutationAction.ABORT:
            lane.status = "aborted"
            await self.storage.update_lane_state(lane)
            return {"status": "aborted"}

        elif task.action == MutationAction.ATTEMPT_START:
            lane.status = "running"
            lane.attempt_count += 1
            await self.storage.update_lane_state(lane)
            return {"attempt_count": lane.attempt_count}

        elif task.action == MutationAction.STEP_ADVANCE:
            new_leaf = task.payload.get("new_leaf_id")
            if new_leaf:
                lane.current_leaf_id = new_leaf
                await self.storage.update_lane_state(lane)
            return {"current_leaf_id": lane.current_leaf_id}

        return {"status": "noop"}
