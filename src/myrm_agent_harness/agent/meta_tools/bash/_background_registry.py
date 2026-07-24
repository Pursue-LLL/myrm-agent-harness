"""In-process registry tracking background bash processes started by the agent.

When ``bash_code_execute_tool`` is invoked with ``run_in_background=True`` the
underlying ``LocalExecutor.spawn_background_process`` returns an
``AsyncProcessProtocol`` handle; this registry keeps that handle alive,
buffers stdout/stderr ring-tail for later inspection, and exposes a tiny CRUD
surface used by ``bash_process_tool``.

Lifetime is the agent process lifetime — orphaned children are killed on
process exit via :mod:`atexit`. Each ``session_id`` has its own bucket so
parallel chats cannot peek at each other's background tasks.

The public data types (``BackgroundProcessInfo``, ``BackgroundQuotaError``,
``FinishListener`` / ``ProgressListener``) live in
:mod:`._background_types` so the registry implementation can focus on
runtime behaviour (process I/O, lifecycle, parsing) without a large type
block, and so downstream consumers can import the snapshot without
dragging in the singleton's ``atexit`` hook.

[INPUT]
- toolkits.code_execution.executors.models::AsyncProcessProtocol (POS: AsyncProcessProtocol — wait/terminate/kill handle.)
- agent.meta_tools.bash._background_types::BackgroundProcessInfo / BackgroundQuotaError / FinishListener / ProgressListener (POS: shared dataclasses & typing.)

[OUTPUT]
- BackgroundProcessRegistry: Process-wide singleton with per-session buckets,
  SIGTERM→SIGKILL grace escalation, 32 KiB line truncation, 300 s reap of
  exited entries, ``last_progress`` snapshot on ``BackgroundProcessInfo``,
  and ``kill_session_jobs`` for cooperative cleanup when an agent session
  is cancelled.
- get_background_registry: Lazy singleton accessor.

[POS]
PTC-adjacent runtime helper. Bash-tool only; no business-layer coupling.
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import signal
import time
from collections import deque
from contextlib import suppress
from threading import Lock
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.meta_tools.bash._background_types import (
    BackgroundProcessInfo,
    BackgroundQuotaError,
    FinishListener,
    ProgressListener,
)
from myrm_agent_harness.agent.meta_tools.bash._background_registry_consume import (
    BackgroundRegistryEntry,
    consume_background_entry,
)
from myrm_agent_harness.utils.os_compat import kill_process_group

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution.executors.models import (
        AsyncProcessProtocol,
    )
    from myrm_agent_harness.agent.meta_tools.bash._background_output_spill import (
        BackgroundOutputSpillWriter,
    )

logger = logging.getLogger(__name__)

_OUTPUT_TAIL_LINES = 200  # Per process; bounded to keep memory flat under churn.
_DEFAULT_PER_SESSION_LIMIT = 5  # Soft cap; raise via env if a power-user complains.
_DEFAULT_KILL_GRACE_SECONDS = 5.0  # SIGTERM → SIGKILL escalation window.
_DEFAULT_REAP_DELAY_SECONDS = (
    300.0  # Exited entries are purged from the registry after this idle window.
)
_WAIT_MAX_SECONDS = 120.0
_WAIT_POLL_INTERVAL_SECONDS = 0.1


class BackgroundProcessRegistry:
    """Process-wide registry of background bash jobs.

    Thread-safe under threading.Lock; reader tasks run on the event loop of
    the caller that registered them, which is fine because the registry only
    interacts with completed snapshots, not the running async I/O.
    """

    def __init__(
        self,
        *,
        per_session_limit: int = _DEFAULT_PER_SESSION_LIMIT,
        reap_delay_seconds: float = _DEFAULT_REAP_DELAY_SECONDS,
    ) -> None:
        self._entries: dict[int, BackgroundRegistryEntry] = {}
        self._lock = Lock()
        self._per_session_limit = per_session_limit
        self._reap_delay_seconds = reap_delay_seconds

    async def register(
        self,
        proc: AsyncProcessProtocol,
        command: str,
        session_id: str | None,
        *,
        finish_listener: FinishListener | None = None,
        progress_listener: ProgressListener | None = None,
    ) -> BackgroundProcessInfo:
        pid = getattr(getattr(proc, "_proc", None), "pid", None)
        if pid is None:  # pragma: no cover — defensive
            raise RuntimeError("background process handle has no PID")

        with self._lock:
            active = sum(
                1
                for e in self._entries.values()
                if e.info.session_id == session_id and e.info.status == "running"
            )
        if active >= self._per_session_limit:
            raise BackgroundQuotaError(session_id, self._per_session_limit)

        from myrm_agent_harness.agent.meta_tools.bash._background_job_store import (
            BackgroundJobStore,
            get_background_job_store,
        )
        from myrm_agent_harness.agent.meta_tools.bash._background_output_spill import (
            BackgroundOutputSpillWriter,
        )

        job_id = BackgroundJobStore.new_job_id()
        started_at = time.time()
        spill_writer: BackgroundOutputSpillWriter | None = None
        if session_id:
            spill_writer = BackgroundOutputSpillWriter(
                session_id=session_id, job_id=job_id
            )

        info = BackgroundProcessInfo(
            job_id=job_id,
            pid=pid,
            command=command,
            session_id=session_id,
            started_at=started_at,
            status="running",
        )
        stdout_buffer: deque[tuple[int, str]] = deque(maxlen=_OUTPUT_TAIL_LINES)
        stderr_buffer: deque[tuple[int, str]] = deque(maxlen=_OUTPUT_TAIL_LINES)
        entry = BackgroundRegistryEntry(
            info=info,
            proc=proc,
            stdout_buffer=stdout_buffer,
            stderr_buffer=stderr_buffer,
            finish_listener=finish_listener,
            progress_listener=progress_listener,
            spill_writer=spill_writer,
        )

        with self._lock:
            self._entries[pid] = entry

        store = get_background_job_store()
        if store is not None and session_id:
            try:
                store.insert_running(
                    job_id=job_id,
                    pid=pid,
                    session_id=session_id,
                    command=command,
                    started_at=started_at,
                )
            except Exception as exc:
                logger.warning(
                    "Background job store insert failed job=%s: %s", job_id, exc
                )

        entry.reader_task = asyncio.create_task(self._consume(entry))
        return info

    def list_processes(
        self, session_id: str | None = None
    ) -> list[BackgroundProcessInfo]:
        with self._lock:
            entries = list(self._entries.values())
        if session_id is None:
            return [self._snapshot(e) for e in entries]
        return [self._snapshot(e) for e in entries if e.info.session_id == session_id]

    def get(self, pid: int) -> BackgroundProcessInfo | None:
        with self._lock:
            entry = self._entries.get(pid)
        return self._snapshot(entry) if entry else None

    def count_running(self, session_id: str | None = None) -> int:
        """Count running background jobs globally or for one session."""
        with self._lock:
            if session_id is None:
                return sum(
                    1
                    for entry in self._entries.values()
                    if entry.info.status == "running"
                )
            return sum(
                1
                for entry in self._entries.values()
                if entry.info.session_id == session_id
                and entry.info.status == "running"
            )

    def get_output(
        self,
        pid: int,
        *,
        max_lines: int = 100,
        since_cursor: int | None = None,
    ) -> dict[str, object]:
        """Return ring-tail snapshot plus a monotonic cursor for incremental polling.

        When ``since_cursor`` is provided only lines whose cursor is strictly
        greater than it are returned, clamped to ``max_lines`` per stream.
        ``next_cursor`` always reflects the registry's current cursor so the
        caller can chain polls without bookkeeping. ``dropped`` is ``True``
        when the ring evicted lines the caller has not yet seen — useful for
        the LLM to know "fetch was incomplete" without scanning content.
        """
        baseline = since_cursor if since_cursor is not None else 0
        with self._lock:
            entry = self._entries.get(pid)
        if entry is None:
            return {
                "stdout": [],
                "stderr": [],
                "next_cursor": baseline,
                "dropped": False,
                "poll_hint": {"has_new_output": False, "suggested_wait_ms": 5000},
            }

        from myrm_agent_harness.agent.meta_tools.bash._background_registry_poll import (
            build_poll_output,
        )

        with self._lock:
            payload, streak = build_poll_output(
                stdout_buffer=entry.stdout_buffer,
                stderr_buffer=entry.stderr_buffer,
                cursor=entry.cursor,
                empty_poll_streak=entry.empty_poll_streak,
                max_lines=max_lines,
                since_cursor=since_cursor,
            )
            if since_cursor is not None:
                entry.empty_poll_streak = streak
        return payload

    async def wait_for_process(
        self,
        pid: int,
        *,
        timeout_seconds: float,
    ) -> dict[str, object]:
        """Wait until a background job exits or ``timeout_seconds`` elapses."""
        capped = min(max(timeout_seconds, 0.0), _WAIT_MAX_SECONDS)
        deadline = time.monotonic() + capped
        while time.monotonic() < deadline:
            info = self.get(pid)
            if info is None:
                return {"found": False, "still_running": False, "pid": pid}
            if info.status != "running":
                return {
                    "found": True,
                    "still_running": False,
                    "pid": pid,
                    "status": info.status,
                    "exit_code": info.exit_code,
                    "error_category": info.error_category,
                }
            await asyncio.sleep(_WAIT_POLL_INTERVAL_SECONDS)
        info = self.get(pid)
        if info is None:
            return {"found": False, "still_running": False, "pid": pid}
        return {
            "found": True,
            "still_running": info.status == "running",
            "pid": pid,
            "status": info.status,
            "exit_code": info.exit_code,
            "error_category": info.error_category,
        }

    async def write_stdin(
        self,
        pid: int,
        data: str,
        *,
        append_newline: bool = False,
        close: bool = False,
    ) -> dict[str, object]:
        """Send data to a running background process stdin (session-agnostic; callers must authorize)."""
        with self._lock:
            entry = self._entries.get(pid)
        if entry is None:
            return {"ok": False, "error": "not_found", "pid": pid}

        from myrm_agent_harness.agent.meta_tools.bash._background_registry_stdin import (
            write_background_stdin,
        )

        return await write_background_stdin(
            entry,
            data,
            append_newline=append_newline,
            close=close,
        )

    async def kill(
        self,
        pid: int,
        *,
        force: bool = False,
        grace_seconds: float = _DEFAULT_KILL_GRACE_SECONDS,
    ) -> bool:
        """Stop a background process, escalating SIGTERM → SIGKILL if needed.

        Signals target the whole process group (POSIX ``killpg`` / Windows
        ``taskkill /T /F``) so forked children (``esbuild`` / ``node``) die
        with the parent and free their ports. With ``force=False`` the
        registry waits up to ``grace_seconds`` and upgrades to SIGKILL on
        timeout — the only reliable way to evict webpack / docker / vite.
        """
        with self._lock:
            entry = self._entries.get(pid)
        if entry is None:
            return False
        if entry.info.status != "running":
            return True

        # 1. Send the initial signal to the *process group* so forked children
        #    (esbuild from vite, node from npm, ffmpeg from a build script,
        #    etc.) die with their parent rather than becoming orphans.
        with suppress(ProcessLookupError, OSError):
            kill_process_group(
                entry.info.pid,
                signal.SIGKILL if force else signal.SIGTERM,
            )

        # 2. For graceful kills wait for the process to exit, then escalate.
        #    For force kills we go straight to cleanup since SIGKILL is
        #    non-catchable.
        if not force and grace_seconds > 0:
            try:
                await asyncio.wait_for(entry.proc.wait(), timeout=grace_seconds)
            except TimeoutError:
                logger.info(
                    "background pid=%s did not exit within %.1fs of SIGTERM; escalating to SIGKILL",
                    pid,
                    grace_seconds,
                )
                with suppress(ProcessLookupError, OSError):
                    kill_process_group(entry.info.pid, signal.SIGKILL)
                with suppress(TimeoutError):
                    await asyncio.wait_for(entry.proc.wait(), timeout=2.0)
            except (ProcessLookupError, OSError):
                pass

        # 3. Mark the entry; the reader task will drain any tail output and
        #    invoke the finish listener via ``_consume``'s ``finally`` block.
        entry.info.status = "killed"
        from myrm_agent_harness.agent.meta_tools.bash._background_registry_store_sync import (
            persist_terminal_state,
        )

        persist_terminal_state(entry.info)
        if entry.reader_task and not entry.reader_task.done():
            entry.reader_task.cancel()
        return True

    async def kill_session_jobs(
        self,
        session_id: str,
        *,
        grace_seconds: float = _DEFAULT_KILL_GRACE_SECONDS,
    ) -> int:
        """Terminate every running background job owned by ``session_id``.

        Invoked by the server when an agent stream is cancelled (user Stop,
        budget exhausted, PWA disconnect grace expiry) so that long-running
        shells (``npm install``, ``webpack --watch``) do not outlive the
        chat and keep eating RAM / CPU / sandbox quota. Returns the number
        of pids actually signalled.

        Kills dispatch *concurrently* via ``asyncio.gather`` so worst-case
        latency is bounded by a single ``grace_seconds`` window rather than
        ``N × grace_seconds``. We snapshot pid+status inside the lock to
        avoid mutating ``self._entries`` while the iterator is live; the
        actual ``kill`` runs lock-free.
        """
        with self._lock:
            targets = [
                entry.info.pid
                for entry in self._entries.values()
                if entry.info.session_id == session_id
                and entry.info.status == "running"
            ]
        if not targets:
            self._maybe_clear_session_spawn_tools(session_id)
            return 0

        results = await asyncio.gather(
            *(self.kill(pid, grace_seconds=grace_seconds) for pid in targets),
            return_exceptions=True,
        )
        killed = sum(1 for r in results if r is True)
        if killed:
            logger.info(
                "background: cancelled session=%s killed=%d/%d jobs (grace=%.1fs)",
                session_id,
                killed,
                len(targets),
                grace_seconds,
            )
        self._maybe_clear_session_spawn_tools(session_id)
        return killed

    def _maybe_clear_session_spawn_tools(self, session_id: str | None) -> None:
        """Drop spawn lifecycle markers when a session has no running shell jobs."""
        if not session_id:
            return
        with self._lock:
            has_running = any(
                entry.info.session_id == session_id and entry.info.status == "running"
                for entry in self._entries.values()
            )
        if has_running:
            return
        from myrm_agent_harness.agent.meta_tools.bash.session_spawn_lifecycle import (
            clear_session_spawn_tools,
        )

        clear_session_spawn_tools(session_id)

    async def _consume(self, entry: BackgroundRegistryEntry) -> None:
        await consume_background_entry(
            entry,
            snapshot=self._snapshot,
            schedule_reap=self._schedule_reap,
            clear_session_if_idle=self._maybe_clear_session_spawn_tools,
        )

    def _schedule_reap(self, pid: int) -> None:
        """Drop an exited/killed entry after a short window so ``list_processes``
        doesn't accumulate history (caps token cost on long sessions).
        """
        if self._reap_delay_seconds <= 0:
            self._drop_entry(pid)
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover — no loop = test setup
            self._drop_entry(pid)
            return
        loop.call_later(self._reap_delay_seconds, self._drop_entry, pid)

    def _drop_entry(self, pid: int) -> None:
        with self._lock:
            entry = self._entries.get(pid)
            if entry is None:
                return
            # Defensive: never reap a still-running entry. ``status`` flips
            # only inside ``_consume`` so by the time the reap callback fires
            # we expect ``exited`` or ``killed``. If something restarts the
            # task with the same PID (PID reuse — extremely rare in our
            # window) we keep it.
            if entry.info.status == "running":
                return
            self._entries.pop(pid, None)

    @staticmethod
    def _snapshot(entry: BackgroundRegistryEntry) -> BackgroundProcessInfo:
        info = entry.info
        snap = BackgroundProcessInfo(
            job_id=info.job_id,
            pid=info.pid,
            command=info.command,
            session_id=info.session_id,
            started_at=info.started_at,
            status=info.status,
            exit_code=info.exit_code,
            error_category=info.error_category,
            vault_log_ref=info.vault_log_ref,
        )
        snap.last_stdout_tail = [text for _, text in list(entry.stdout_buffer)[-20:]]
        snap.last_stderr_tail = [text for _, text in list(entry.stderr_buffer)[-20:]]
        # Defensive shallow copy: callers serialise this dict into JSON; any
        # in-place mutation by the consumer must not bleed back into the
        # live registry record (parsers append/normalise fields downstream).
        snap.last_progress = dict(info.last_progress) if info.last_progress else None
        return snap

    def shutdown(self) -> None:
        """Group-SIGKILL every still-running child on interpreter exit.

        Mirrors the ``kill`` contract so forked grandchildren
        (``node`` / ``esbuild`` under ``npm start``) die with the leader.
        ``atexit`` is synchronous; live callers should use ``kill`` for grace.
        """
        with self._lock:
            entries = list(self._entries.values())
        for entry in entries:
            if entry.info.status != "running":
                continue
            with suppress(ProcessLookupError, OSError):
                kill_process_group(entry.info.pid, signal.SIGKILL)


_registry: BackgroundProcessRegistry | None = None
_registry_lock = Lock()


def get_background_registry() -> BackgroundProcessRegistry:
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = BackgroundProcessRegistry()
            atexit.register(_registry.shutdown)
        return _registry


__all__ = [
    "BackgroundProcessInfo",
    "BackgroundProcessRegistry",
    "BackgroundQuotaError",
    "FinishListener",
    "ProgressListener",
    "get_background_registry",
]
