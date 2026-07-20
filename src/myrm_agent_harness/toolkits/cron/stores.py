"""Built-in in-memory CronStore for development and testing.

Data lives only in process memory — lost on restart.
NOT suitable for production; use a database-backed store instead.

Thread-safe for asyncio (single event loop) via ``asyncio.Lock``.

[INPUT]
- infra.incremental.types::MonitorState (POS: Domain types for incremental monitoring.)

[OUTPUT]
- InMemoryCronStore: CronStore backed by plain dicts — zero external dependenc...

[POS]
Built-in in-memory CronStore for development and testing.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime

from myrm_agent_harness.infra.incremental.types import MonitorState
from myrm_agent_harness.toolkits.cron.types import (
    CronJob,
    CronRunRecord,
    JobStatus,
)


class InMemoryCronStore:
    """CronStore backed by plain dicts — zero external dependencies.

    Intended for local development, unit tests, and quick prototyping.
    All mutations return deep copies to prevent aliasing bugs.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, CronJob] = {}
        self._runs: list[CronRunRecord] = []
        self._monitors: dict[str, MonitorState] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Job CRUD
    # ------------------------------------------------------------------

    async def list_jobs(
        self,
        *,
        user_id: str | None = None,
        name_filter: str | None = None,
        chat_id: str | None = None,
        due_before: datetime | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[CronJob]:
        async with self._lock:
            result = list(self._jobs.values())

        if user_id is not None:
            result = [j for j in result if j.user_id == user_id]

        if chat_id is not None:
            result = [j for j in result if j.chat_id == chat_id]

        if name_filter is not None:
            name_filter_lower = name_filter.lower()
            result = [j for j in result if name_filter_lower in j.name.lower()]

        if due_before is not None:
            result = [
                j
                for j in result
                if j.status == JobStatus.ACTIVE and j.next_run_at is not None and j.next_run_at <= due_before
            ]
        else:
            result.sort(key=lambda j: j.created_at, reverse=True)

        result = result[offset:]
        if limit is not None:
            result = result[:limit]
        return [deepcopy(j) for j in result]

    async def count_jobs(
        self,
        *,
        user_id: str | None = None,
        name_filter: str | None = None,
        chat_id: str | None = None,
    ) -> int:
        async with self._lock:
            jobs = list(self._jobs.values())
        if user_id is not None:
            jobs = [j for j in jobs if j.user_id == user_id]
        if chat_id is not None:
            jobs = [j for j in jobs if j.chat_id == chat_id]
        if name_filter is not None:
            name_filter_lower = name_filter.lower()
            jobs = [j for j in jobs if name_filter_lower in j.name.lower()]
        return len(jobs)

    async def get_job(self, job_id: str) -> CronJob | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            return deepcopy(job) if job else None

    async def earliest_next_run(self) -> datetime | None:
        async with self._lock:
            times = [
                j.next_run_at for j in self._jobs.values() if j.status == JobStatus.ACTIVE and j.next_run_at is not None
            ]
        return min(times) if times else None

    async def save_job(self, job: CronJob) -> CronJob:
        async with self._lock:
            saved = deepcopy(job)
            saved.updated_at = datetime.now(UTC)
            self._jobs[saved.id] = saved
            return deepcopy(saved)

    async def delete_job(self, job_id: str) -> bool:
        async with self._lock:
            return self._jobs.pop(job_id, None) is not None

    async def claim_due(self, job_ids: list[str]) -> None:
        async with self._lock:
            for jid in job_ids:
                job = self._jobs.get(jid)
                if job:
                    job.next_run_at = None

    # ------------------------------------------------------------------
    # Run records
    # ------------------------------------------------------------------

    async def save_run(self, run: CronRunRecord) -> None:
        async with self._lock:
            self._runs.append(run)

    async def list_runs(
        self,
        job_id: str | None = None,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> list[CronRunRecord]:
        async with self._lock:
            result = list(self._runs)

        if job_id is not None:
            result = [r for r in result if r.job_id == job_id]
        if status:
            result = [r for r in result if r.status == status]

        result.sort(key=lambda r: r.started_at, reverse=True)
        return result[offset : offset + limit]

    async def count_runs(
        self,
        job_id: str | None = None,
        *,
        status: str | None = None,
    ) -> int:
        async with self._lock:
            runs = self._runs
            if job_id is not None:
                runs = [r for r in runs if r.job_id == job_id]
            if status:
                runs = [r for r in runs if r.status == status]
            return len(runs)

    async def list_orphaned_active(self) -> list[CronJob]:
        async with self._lock:
            return [deepcopy(j) for j in self._jobs.values() if j.status == JobStatus.ACTIVE and j.next_run_at is None]

    async def purge_old_runs(self, before: datetime) -> int:
        async with self._lock:
            original = len(self._runs)
            self._runs = [r for r in self._runs if r.finished_at >= before]
            return original - len(self._runs)

    async def get_latest_integrity_hash(self, job_id: str) -> str | None:
        async with self._lock:
            matching = [r for r in self._runs if r.job_id == job_id and r.integrity_hash]
        if not matching:
            return None
        matching.sort(key=lambda r: r.started_at, reverse=True)
        return matching[0].integrity_hash

    async def delete_job_cascade(self, job_id: str) -> bool:
        async with self._lock:
            self._monitors.pop(job_id, None)
            self._runs = [r for r in self._runs if r.job_id != job_id]
            return self._jobs.pop(job_id, None) is not None

    # ------------------------------------------------------------------
    # Monitor state
    # ------------------------------------------------------------------

    async def get_monitor_state(self, job_id: str) -> MonitorState | None:
        async with self._lock:
            state = self._monitors.get(job_id)
            return deepcopy(state) if state else None

    async def save_monitor_state(self, state: MonitorState) -> None:
        async with self._lock:
            self._monitors[state.job_id] = deepcopy(state)

    async def delete_monitor_state(self, job_id: str) -> bool:
        async with self._lock:
            return self._monitors.pop(job_id, None) is not None

    async def batch_get_monitor_states(self, job_ids: list[str]) -> dict[str, MonitorState]:
        async with self._lock:
            return {jid: deepcopy(self._monitors[jid]) for jid in job_ids if jid in self._monitors}
