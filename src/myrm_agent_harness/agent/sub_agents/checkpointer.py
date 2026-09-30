"""Shared SQLite checkpointer for subagents.

[INPUT]
- MYRM_DATA_DIR / CHECKPOINTER_MODE / SUBAGENT_CHECKPOINT_DB_PATH env vars
- langgraph.checkpoint.base::BaseCheckpointSaver
- langgraph.checkpoint.sqlite.aio::AsyncSqliteSaver
- langgraph.checkpoint.memory::InMemorySaver
- myrm_agent_harness.runtime.checkpointing.factory::PickleSerde
- myrm_agent_harness.utils.db.sqlite::DEFAULT, harden_connection_async

[OUTPUT]
- get_subagent_checkpointer: shared checkpointer singleton (SubagentSqliteCheckpointer or InMemorySaver)
- close_subagent_checkpointer: release underlying SQLite connection on shutdown
- reset_subagent_checkpointer: clear singleton instance (for clean test isolation)
- delete_subagent_checkpoint: drop a finished subagent thread (memory & disk hygiene)
- drop_subagent_checkpoint_if_terminal: SSOT gate dropping thread on non-approval completion

[POS]
HITL approval for subagents requires a configured checkpointer (approval/middleware.py
requires it so GraphInterrupt state survives the child run). Each subagent uses
thread_id == task_id (set via context["approval_session_key"]), so one shared
checkpointer instance keeps threads isolated per subagent and lets a resume pass
(Command(resume=...)) restore the interrupted graph from the same thread.

The shared saver is intentionally NOT the parent agent's checkpointer: subagent
message history stays in its own thread and never pollutes the parent thread
(see SUB_AGENT_SYSTEM.md §7).

Persistence & Resilience:
- Defaults to SQLite on persistent volume ({MYRM_DATA_DIR}/subagent_checkpoints.sqlite).
- Falls back to InMemorySaver when CHECKPOINTER_MODE=memory.
- In test environments (PYTEST_CURRENT_TEST), defaults to an in-memory SQLite backend
  or isolated test directory to prevent state pollution.
- Concurrency-hardened via SQLite WAL mode and busy_timeout.

Memory hygiene: delete_subagent_checkpoint() drops the thread once a subagent
reaches a terminal (non-approval) status. PENDING_APPROVAL threads are kept so
the resume pass can restore them.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.checkpoint.memory import InMemorySaver

if TYPE_CHECKING:
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from myrm_agent_harness.agent.sub_agents.types import SubAgentStatus

logger = logging.getLogger(__name__)

_checkpointer_lock = asyncio.Lock()
_subagent_checkpointer: BaseCheckpointSaver[str] | None = None
_cleanup_tasks: set[asyncio.Task[None]] = set()


def resolve_subagent_checkpoint_db_path() -> str:
    """Resolve the SQLite database path for subagent checkpoints based on environment."""
    explicit_path = os.environ.get("SUBAGENT_CHECKPOINT_DB_PATH")
    if explicit_path:
        return explicit_path

    # In active unit/integration test suites, isolate to :memory: if not explicitly specified
    if "PYTEST_CURRENT_TEST" in os.environ or os.environ.get("TESTING") == "1":
        return ":memory:"

    data_dir = os.environ.get("MYRM_DATA_DIR")
    if data_dir:
        return str(Path(data_dir) / "subagent_checkpoints.sqlite")

    default_dir = Path.home() / ".myrm" / "data"
    return str(default_dir / "subagent_checkpoints.sqlite")


class SubagentSqliteCheckpointer(BaseCheckpointSaver[str]):
    """Thread-safe lazy-initialized SQLite checkpointer proxy for subagent runs.

    Defers aiosqlite connection establishment and schema setup until the first
    async operation inside an active event loop. Guarantees zero blocking during
    synchronous construction and safe thread-level isolation.
    """

    def __init__(self, db_path: str) -> None:
        super().__init__()
        self._db_path = db_path
        self._saver: AsyncSqliteSaver | None = None
        self._conn: aiosqlite.Connection | None = None
        self._init_lock = asyncio.Lock()

    async def _ensure_saver(self) -> AsyncSqliteSaver:
        if self._saver is not None:
            return self._saver
        async with self._init_lock:
            if self._saver is not None:
                return self._saver

            import aiosqlite
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

            from myrm_agent_harness.runtime.checkpointing.factory import PickleSerde
            from myrm_agent_harness.utils.db.sqlite import DEFAULT, harden_connection_async

            db_target = self._db_path
            conn: aiosqlite.Connection | None = None
            if db_target != ":memory:":
                try:
                    Path(db_target).parent.mkdir(parents=True, exist_ok=True)
                    conn = await aiosqlite.connect(db_target)
                except (OSError, aiosqlite.Error, sqlite3.OperationalError) as err:
                    logger.warning(
                        "[SubagentCheckpointer] Failed to open SQLite checkpointer at %s (%s). Falling back to :memory:.",
                        db_target,
                        err,
                    )
                    db_target = ":memory:"
                    conn = None

            if conn is None:
                conn = await aiosqlite.connect(":memory:")

            await harden_connection_async(conn, DEFAULT, db_path=Path(db_target) if db_target != ":memory:" else None)

            saver = AsyncSqliteSaver(conn, serde=PickleSerde())
            await saver.setup()

            self._conn = conn
            self._saver = saver
            logger.info("[SubagentCheckpointer] SQLite checkpointer initialized at %s", db_target)
            return self._saver

    @staticmethod
    def _normalize_config(config: RunnableConfig) -> RunnableConfig:
        configurable = dict(config.get("configurable") or {})
        if "checkpoint_ns" not in configurable:
            configurable["checkpoint_ns"] = ""
        norm_config = dict(config)
        norm_config["configurable"] = configurable
        return norm_config

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        saver = await self._ensure_saver()
        return await saver.aget_tuple(self._normalize_config(config))

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, object] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        saver = await self._ensure_saver()
        norm_cfg = self._normalize_config(config) if config is not None else None
        norm_before = self._normalize_config(before) if before is not None else None
        async for item in saver.alist(norm_cfg, filter=filter, before=norm_before, limit=limit):
            yield item

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        saver = await self._ensure_saver()
        return await saver.aput(self._normalize_config(config), checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, object]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        saver = await self._ensure_saver()
        await saver.aput_writes(self._normalize_config(config), writes, task_id, task_path=task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        if self._saver is None:
            # If saver was never initialized, no checkpoints were ever stored; safe no-op
            return
        await self._saver.adelete_thread(thread_id)

    async def aclose(self) -> None:
        """Release underlying aiosqlite connection safely."""
        async with self._init_lock:
            if self._conn is not None:
                try:
                    await self._conn.close()
                except Exception as exc:
                    logger.debug("[SubagentCheckpointer] Error during SQLite close: %s", exc)
                finally:
                    self._conn = None
                    self._saver = None
                logger.info("[SubagentCheckpointer] SQLite connection closed")


def get_subagent_checkpointer() -> BaseCheckpointSaver[str]:
    """Return the process-wide shared checkpointer for subagent threads.

    Lazy singleton: created on first use. Mode is determined by CHECKPOINTER_MODE:
    - 'memory': uses pure InMemorySaver (lightweight, ephemeral)
    - default/other: uses SubagentSqliteCheckpointer (crash-resilient, Volume-persisted)
    """
    global _subagent_checkpointer
    if _subagent_checkpointer is None:
        mode = os.environ.get("CHECKPOINTER_MODE", "").lower()
        if mode == "memory":
            _subagent_checkpointer = InMemorySaver()
        else:
            db_path = resolve_subagent_checkpoint_db_path()
            _subagent_checkpointer = SubagentSqliteCheckpointer(db_path)
    return _subagent_checkpointer


async def close_subagent_checkpointer() -> None:
    """Close underlying database connection for subagent checkpointer."""
    global _subagent_checkpointer
    async with _checkpointer_lock:
        if _subagent_checkpointer is not None:
            if isinstance(_subagent_checkpointer, SubagentSqliteCheckpointer):
                await _subagent_checkpointer.aclose()
            _subagent_checkpointer = None


def reset_subagent_checkpointer() -> None:
    """Synchronously reset singleton state for test isolation and gracefully close active connection."""
    global _subagent_checkpointer
    old_saver = _subagent_checkpointer
    _subagent_checkpointer = None
    if isinstance(old_saver, SubagentSqliteCheckpointer):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            if loop.is_running():
                task = loop.create_task(old_saver.aclose())
                _cleanup_tasks.add(task)
                task.add_done_callback(_cleanup_tasks.discard)


async def delete_subagent_checkpoint(thread_id: str) -> None:
    """Drop a finished subagent thread from the shared checkpointer.

    Called by the subagent executor once a run reaches a terminal status that is
    not PENDING_APPROVAL (approval threads must survive for the resume pass).
    Safe to call for unknown thread ids (no-op).
    """
    saver = _subagent_checkpointer
    if saver is None:
        return
    try:
        async with _checkpointer_lock:
            await saver.adelete_thread(thread_id)
    except Exception:
        # Deletion is best-effort hygiene; never break the executor for it.
        pass


async def drop_subagent_checkpoint_if_terminal(task_id: str, status: SubAgentStatus | str) -> None:
    """Delete subagent checkpoint thread if the subagent reached a non-approval terminal status.

    Keeps the thread when status is PENDING_APPROVAL so the resume pass can restore the interrupted graph.
    All other terminal statuses (COMPLETED, FAILED, CANCELLED, TIMED_OUT, etc.) drop the thread to prevent
    unbounded SQLite database bloat.
    """
    from myrm_agent_harness.agent.sub_agents.types import SubAgentStatus

    if status is SubAgentStatus.PENDING_APPROVAL or status == "pending_approval":
        return
    await delete_subagent_checkpoint(task_id)


# Backward-compatible alias for existing tests/internals
_drop_finished_subagent_thread = drop_subagent_checkpoint_if_terminal
