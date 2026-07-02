"""Protocols for the cron toolkit.

Six contracts that the application layer must satisfy:

- ``CronStore``        — persistence (17 methods, unified for scheduler & manager)
- ``JobRunner``        — execute a single job and produce a ``JobResult``
- ``ResultDelivery``   — push results to the user via some channel
- ``ConcurrencyLock``  — optional lock for cross-process coordination (Leader election)
- ``TriggerProvider``  — optional event/webhook/poll trigger matching
- ``StreamListener``   — optional outbound stream (WS/SSE) lifecycle management

[INPUT]
- infra.incremental.types::MonitorState (POS: Domain types for incremental monitoring.)

[OUTPUT]
- CronStore: Persistence contract for cron jobs and run records.
- JobRunner: Executes a single cron job and returns the result.
- ResultDelivery: Delivers job results to the user via their configured cha...
- ConcurrencyLock: Optional lock for leader election or cross-process coordi...
- TriggerProvider: Optional trigger provider for event-driven job execution.
- StreamListener: Manages outbound WS/SSE stream connections for real-time ...

[POS]
Protocols for the cron toolkit.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from myrm_agent_harness.infra.incremental.types import MonitorState
    from myrm_agent_harness.toolkits.cron.triggers import StreamTrigger
    from myrm_agent_harness.toolkits.cron.types import CronJob, CronRunRecord, JobResult


# ---------------------------------------------------------------------------
# CronStore — unified persistence
# ---------------------------------------------------------------------------


@runtime_checkable
class CronStore(Protocol):
    """Persistence contract for cron jobs and run records.

    All datetime values are UTC.  ``user_id`` filtering and authorization
    are handled by ``CronManager`` — the store itself is auth-agnostic.
    """

    async def list_jobs(
        self,
        *,
        user_id: str | None = None,
        name_filter: str | None = None,
        due_before: datetime | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[CronJob]:
        """Return jobs matching the given filters.

        - ``user_id`` set: return all jobs owned by that user.
        - ``name_filter`` set: fuzzy match job names (LIKE %filter%).
        - ``due_before`` set: return active jobs whose ``next_run_at <= due_before``.
        - Both None: return all jobs (admin use only).
        - ``limit``/``offset``: optional pagination (None = no limit).
        """
        ...

    async def count_jobs(self, *, user_id: str | None = None) -> int:
        """Count jobs matching the given filters."""
        ...

    async def get_job(self, job_id: str) -> CronJob | None:
        """Return a single job by ID, or None."""
        ...

    async def earliest_next_run(self) -> datetime | None:
        """Return the earliest ``next_run_at`` across all active jobs, or None."""
        ...

    async def save_job(self, job: CronJob) -> CronJob:
        """Create or update a job (upsert semantics).

        Returns the persisted job (may differ in ``updated_at`` etc.).
        """
        ...

    async def delete_job(self, job_id: str) -> bool:
        """Delete a job by ID.  Returns True if a row was deleted."""
        ...

    async def claim_due(self, job_ids: list[str]) -> None:
        """Atomically mark the given jobs as claimed for execution.

        Typically sets ``next_run_at = NULL`` so they won't be picked up again.
        Must be an atomic operation to ensure cross-process safety.
        """
        ...

    async def save_run(self, run: CronRunRecord) -> None:
        """Persist a run record."""
        ...

    async def list_runs(
        self,
        job_id: str | None = None,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> list[CronRunRecord]:
        """Return recent run records, newest first.

        When ``job_id`` is None, returns runs across all jobs (global view).
        """
        ...

    async def count_runs(
        self,
        job_id: str | None = None,
        *,
        status: str | None = None,
    ) -> int:
        """Count run records matching the given filters."""
        ...

    async def list_orphaned_active(self) -> list[CronJob]:
        """Return ACTIVE jobs with ``next_run_at IS NULL``.

        These are jobs that were claimed for execution (next_run_at cleared
        by ``claim_due``) but never completed — typically due to a process
        crash.  The scheduler uses this during startup recovery to detect
        and heal stale runs.
        """
        ...

    async def purge_old_runs(self, before: datetime) -> int:
        """Delete run records older than ``before``.

        Returns the number of deleted rows.  Called periodically by the
        scheduler to prevent unbounded growth of the run history table.
        """
        ...

    async def get_latest_integrity_hash(self, job_id: str) -> str | None:
        """Return the ``integrity_hash`` of the most recent run for a job.

        Used by the executor to chain the next run's Merkle hash.
        Returns None if the job has no prior runs (or no hashed runs).
        """
        ...

    async def delete_job_cascade(self, job_id: str) -> bool:
        """Delete a job and all associated run records.

        Returns True if the job existed and was deleted.  Preferred over
        ``delete_job`` when cleaning up to avoid orphaned run records.
        """
        ...

    async def get_monitor_state(self, job_id: str) -> MonitorState | None:
        """Return the monitor state for a job, or None if not found.

        Used by ``IncrementalMonitorManager`` to restore monitor instances.
        """
        ...

    async def save_monitor_state(self, state: MonitorState) -> None:
        """Persist monitor state for a job (upsert semantics).

        Args:
            state: Monitor state to persist.
        """
        ...

    async def delete_monitor_state(self, job_id: str) -> bool:
        """Delete monitor state for a job.

        Returns True if state existed and was deleted.
        Called when a job is deleted or monitor config is cleared.
        """
        ...

    async def batch_get_monitor_states(self, job_ids: list[str]) -> dict[str, MonitorState]:
        """Batch get monitor states for multiple jobs.

        Args:
            job_ids: List of job identifiers.

        Returns:
            Dict mapping job_id to MonitorState. Missing jobs are omitted.
            Used to eliminate N+1 queries in list_jobs endpoint.
        """
        ...


# ---------------------------------------------------------------------------
# PreFlightCondition — script injection
# ---------------------------------------------------------------------------


@runtime_checkable
class PreFlightCondition(Protocol):
    """Evaluates whether a job should run and returns injected context.

    Invoked by JobExecutor before run().
    """

    async def evaluate(self, job: CronJob) -> tuple[bool, str]:
        """Evaluate the condition.

        Returns:
            A tuple of (should_run, injected_context).
            - if should_run is False, job execution is aborted.
            - injected_context is appended to the agent's input context.
        """
        ...


# ---------------------------------------------------------------------------
# JobRunner — single-job executor
# ---------------------------------------------------------------------------


@runtime_checkable
class JobRunner(Protocol):
    """Executes a single cron job and returns the result.

    The application layer provides concrete runners keyed by ``JobType``.

    ``context`` carries ephemeral data from the triggering event (e.g.
    webhook payload, matched message).  Runners may inject this into
    the execution environment (prompt, env var, etc.).  Empty string
    means no trigger context — backward-compatible default.
    """

    async def run(self, job: CronJob, *, context: str = "") -> JobResult: ...


# ---------------------------------------------------------------------------
# ResultDelivery — push results to the user
# ---------------------------------------------------------------------------


@runtime_checkable
class ResultDelivery(Protocol):
    """Delivers job results to the user via their configured channel."""

    async def deliver(self, job: CronJob, result: JobResult) -> None: ...


# ---------------------------------------------------------------------------
# ConcurrencyLock — optional, for multi-worker scheduler
# ---------------------------------------------------------------------------


@runtime_checkable
class ConcurrencyLock(Protocol):
    """Optional lock for leader election or cross-process coordination.

    When multiple scheduler processes run against the same DB, only the lock holder ticks.
    The implementation must handle automatic renewal internally.

    Lifecycle: ``try_acquire`` at start, ``release`` at stop.
    """

    async def try_acquire(self, name: str, ttl_seconds: int = 60) -> bool:
        """Attempt to acquire a named lock.

        Returns True if acquired.  Must start automatic renewal
        to prevent expiration while the holder is alive.
        """
        ...

    async def release(self, name: str) -> None:
        """Release the named lock and stop renewal."""
        ...


# ---------------------------------------------------------------------------
# TriggerProvider — optional event/webhook/poll trigger matching
# ---------------------------------------------------------------------------


@runtime_checkable
class TriggerProvider(Protocol):
    """Optional trigger provider for event-driven job execution.

    The application layer implements this protocol to enable non-cron
    triggers (message events, webhooks, system events).  Injected into
    the scheduler at construction time; when absent, only time-based
    scheduling is available.
    """

    async def check_event_triggers(
        self,
        message: str,
        channel: str,
        user_id: str,
    ) -> list[CronJob]:
        """Return jobs whose event triggers match the incoming message."""
        ...

    async def check_system_event(
        self,
        source: str,
        event_type: str,
        payload: dict[str, object],
    ) -> list[CronJob]:
        """Return jobs whose system-event triggers match the event."""
        ...

    async def handle_webhook(
        self,
        path: str,
        secret: str,
        payload: dict[str, object],
    ) -> CronJob | None:
        """Validate and return the job matching the webhook path + secret."""
        ...


# ---------------------------------------------------------------------------
# StreamListener — outbound stream (WS/SSE) lifecycle management
# ---------------------------------------------------------------------------

StreamEventCallback = Callable[[str, str, str], Coroutine[None, None, None]]
"""Async callback ``(job_id, trigger_url, matched_payload) -> None``.

Invoked by the ``StreamListener`` implementation when a stream event
matches the trigger's filter criteria.  The application layer wires this
to ``JobExecutor.fire(job, context=matched_payload)``.
"""


@runtime_checkable
class StreamListener(Protocol):
    """Manages outbound WS/SSE stream connections for real-time event triggers.

    The application layer implements this protocol to maintain persistent
    outbound connections that listen for events matching ``StreamTrigger``
    configurations.  This enables real-time monitoring even behind NAT
    (Local WebUI, Tauri desktop) where inbound webhooks are impossible.

    Lifecycle: ``start_stream`` when a job with ``StreamTrigger`` is created
    or activated, ``stop_stream`` on delete/pause, ``stop_all`` on shutdown.
    """

    async def start_stream(
        self,
        job_id: str,
        trigger: StreamTrigger,
        on_event: StreamEventCallback,
    ) -> None:
        """Establish an outbound stream connection for the given trigger.

        The implementation must handle reconnection with exponential backoff,
        heartbeat/ping for connection health, and filter matching (json_path +
        regex) before invoking ``on_event``.

        Raises ``ValueError`` if the ``trigger.url`` fails SSRF validation.
        """
        ...

    async def stop_stream(self, job_id: str) -> None:
        """Tear down the stream connection for the given job.

        No-op if no active stream exists for ``job_id``.
        """
        ...

    async def stop_all(self) -> None:
        """Tear down all active stream connections (graceful shutdown)."""
        ...

    def active_streams(self) -> dict[str, str]:
        """Return ``{job_id: stream_url}`` for all active connections.

        Used by the frontend status indicator and health checks.
        """
        ...
