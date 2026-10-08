"""Task Lease Governor and Cascade Termination Executor.

[POS]
Maintains micro-lease tickets and real-time reverse resource indexes for in-flight tasks.
Enforces execution-time assertions and triggers ≤100ms 3-level cascade termination
(async task cancellation -> process SIGTERM/SIGKILL -> ephemeral context scrubbing).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from uuid import uuid4

from myrm_agent_harness.agent.security.lease.models import (
    LeaseTicket,
    RevocationEvent,
    RevocationSubjectType,
    RevocationTerminatedError,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RegisteredTaskContext:
    """Execution context and active resources registered for an in-flight task."""

    task_id: str
    asyncio_task: asyncio.Task[object] | None = None
    process_pids: set[int] = field(default_factory=set)
    scrub_hooks: list[Callable[[], None | Awaitable[None]]] = field(default_factory=list)


class CascadeTerminationExecutor:
    """Executes 3-level cascade termination for a revoked task context."""

    @classmethod
    async def terminate_task_context(
        cls,
        context: RegisteredTaskContext,
        event: RevocationEvent,
    ) -> None:
        """Execute async task cancellation, process kill, and context scrubbing."""
        task_id = context.task_id
        logger.warning(
            "[CASCADE_KILL] Terminating task %s due to revocation of [%s:%s] (Reason: %s)",
            task_id,
            event.subject_type.value,
            event.subject_id,
            event.reason,
        )

        # Level 1: In-Flight Async Task Cancellation
        if context.asyncio_task is not None and not context.asyncio_task.done():
            context.asyncio_task.cancel()

        # Level 2: Physical Sandbox/Process SIGTERM -> SIGKILL
        for pid in list(context.process_pids):
            cls._kill_process(pid, hard_kill=(event.grace_period_ms == 0))

        # Level 3: Ephemeral Context Scrubbing
        for hook in context.scrub_hooks:
            try:
                res = hook()
                if asyncio.iscoroutine(res):
                    await res
            except Exception as exc:
                logger.error("[CASCADE_KILL] Scrub hook failed for task %s: %s", task_id, exc)

    @staticmethod
    def _kill_process(pid: int, hard_kill: bool = True) -> None:
        """Kill a physical process group or PID."""
        try:
            sig = signal.SIGKILL if hard_kill else signal.SIGTERM
            os.kill(pid, sig)
            logger.info("[CASCADE_KILL] Sent signal %s to process %d", sig.name, pid)
        except ProcessLookupError:
            pass
        except Exception as exc:
            logger.warning("[CASCADE_KILL] Failed to send signal to process %d: %s", pid, exc)


class TaskLeaseGovernor:
    """Governor managing micro-leases and in-flight revocation broadcasts."""

    _instance: TaskLeaseGovernor | None = None
    _singleton_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._leases: dict[str, LeaseTicket] = {}
        self._resource_index: dict[str, set[str]] = {}
        self._task_contexts: dict[str, RegisteredTaskContext] = {}

    @classmethod
    def get_instance(cls) -> TaskLeaseGovernor:
        """Obtain process-wide singleton governor instance."""
        if cls._instance is None:
            with cls._singleton_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton for testing isolation."""
        with cls._singleton_lock:
            cls._instance = None

    def register_task(
        self,
        task_id: str,
        asyncio_task: asyncio.Task[object] | None = None,
        process_pids: set[int] | None = None,
        scrub_hooks: list[Callable[[], None | Awaitable[None]]] | None = None,
    ) -> None:
        """Register execution handles for an in-flight task."""
        with self._lock:
            ctx = self._task_contexts.get(task_id)
            if ctx is None:
                ctx = RegisteredTaskContext(
                    task_id=task_id,
                    asyncio_task=asyncio_task,
                    process_pids=set(process_pids or ()),
                    scrub_hooks=list(scrub_hooks or ()),
                )
                self._task_contexts[task_id] = ctx
            else:
                if asyncio_task is not None:
                    ctx.asyncio_task = asyncio_task
                if process_pids:
                    ctx.process_pids.update(process_pids)
                if scrub_hooks:
                    ctx.scrub_hooks.extend(scrub_hooks)

    def acquire_lease(
        self,
        task_id: str,
        bound_resources: set[str] | frozenset[str],
        ttl_seconds: float = 30.0,
    ) -> LeaseTicket:
        """Acquire a time-bound micro-lease and index its bound security resources."""
        frozen_resources = frozenset(bound_resources)
        ticket = LeaseTicket(
            ticket_id=uuid4().hex,
            task_id=task_id,
            bound_resources=frozen_resources,
            expires_at=time.time() + ttl_seconds,
            ttl_seconds=ttl_seconds,
        )

        with self._lock:
            self._leases[task_id] = ticket
            for res_id in frozen_resources:
                self._resource_index.setdefault(res_id, set()).add(task_id)

        return ticket

    def renew_lease(self, task_id: str, ttl_seconds: float = 30.0) -> bool:
        """Extend the micro-lease for an active task if not revoked."""
        with self._lock:
            ticket = self._leases.get(task_id)
            if ticket is None:
                return False
            self._leases[task_id] = ticket.renew(ttl_seconds)
            return True

    def assert_lease_valid(self, task_id: str) -> None:
        """Assert that an in-flight task holds a valid, unexpired micro-lease.

        Raises:
            RevocationTerminatedError: If lease was revoked or expired.
        """
        with self._lock:
            ticket = self._leases.get(task_id)

        if ticket is None:
            raise RevocationTerminatedError(
                task_id=task_id,
                subject_id="all_resources",
                subject_type=RevocationSubjectType.RESOURCE,
                reason="No active lease ticket held for task (lease revoked or not acquired)",
            )

        if ticket.is_expired:
            raise RevocationTerminatedError(
                task_id=task_id,
                subject_id="lease_expiry",
                subject_type=RevocationSubjectType.SESSION,
                reason="Task lease expired without renewal (possible heartbeat failure)",
            )

    async def revoke_subject(self, event: RevocationEvent) -> int:
        """Revoke a security subject, invalidate all related leases, and cascade kill tasks.

        Returns:
            The number of in-flight tasks terminated.
        """
        target_task_ids: set[str] = set()

        with self._lock:
            # 1. Subject is a specific resource identifier
            if event.subject_id in self._resource_index:
                target_task_ids.update(self._resource_index[event.subject_id])

            # 2. Subject is a direct task / session ID
            if event.subject_id in self._leases:
                target_task_ids.add(event.subject_id)

            # Invalidate all identified leases immediately
            for tid in target_task_ids:
                ticket = self._leases.pop(tid, None)
                if ticket:
                    for res_id in ticket.bound_resources:
                        tasks = self._resource_index.get(res_id)
                        if tasks:
                            tasks.discard(tid)
                            if not tasks:
                                self._resource_index.pop(res_id, None)

        if not target_task_ids:
            logger.info(
                "[LEASE_GOVERNOR] Revocation broadcast received for [%s:%s], no active in-flight tasks affected",
                event.subject_type.value,
                event.subject_id,
            )
            return 0

        logger.warning(
            "[LEASE_GOVERNOR] Revoking %d in-flight tasks for [%s:%s]",
            len(target_task_ids),
            event.subject_type.value,
            event.subject_id,
        )

        # Execute cascade terminations
        for tid in target_task_ids:
            with self._lock:
                ctx = self._task_contexts.pop(tid, None)
            if ctx is not None:
                await CascadeTerminationExecutor.terminate_task_context(ctx, event)

        return len(target_task_ids)

    def release_task(self, task_id: str) -> None:
        """Release all lease and tracking records when a task completes normally."""
        with self._lock:
            ticket = self._leases.pop(task_id, None)
            if ticket:
                for res_id in ticket.bound_resources:
                    tasks = self._resource_index.get(res_id)
                    if tasks:
                        tasks.discard(task_id)
                        if not tasks:
                            self._resource_index.pop(res_id, None)
            self._task_contexts.pop(task_id, None)
