"""Checkpointer factory — encapsulates creation, configuration, and cleanup.

[INPUT]
- DEPLOY_MODE / CHECKPOINTER_MODE env vars
- langgraph checkpoint savers (sqlite / memory)
- myrm_agent_harness.toolkits.browser.checkpoint (ThreadStore, IncrementalSessionCheckpointer)

[OUTPUT]
- create_checkpointer(): returns (BaseCheckpointSaver, cleanup_callback)

[POS]
Checkpointer decision logic (SQLite / Memory selection),
database connection management, and resource cleanup.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import aiosqlite
    from langgraph.checkpoint.base import BaseCheckpointSaver

logger = logging.getLogger(__name__)

_LARGE_CHECKPOINT_THRESHOLD = 102400  # 100KB


class PickleSerde:
    """Pickle-based serializer for LangGraph checkpoints.

    Uses dill for enhanced serialization to support complex objects (e.g., ChatLiteLLM)
    that contain module references. Falls back to pickle on failure.

    Typical checkpoint size: 3-10KB (verified via testing).
    """

    def dumps_typed(self, obj: object) -> tuple[str, bytes]:
        try:
            import dill

            serialized = dill.dumps(obj)
            type_prefix = "dill"
        except Exception as e:
            logger.warning("dill serialization failed, fallback to pickle: %s", e)
            import pickle

            serialized = pickle.dumps(obj)
            type_prefix = "pickle"

        size = len(serialized)
        if size > _LARGE_CHECKPOINT_THRESHOLD:
            logger.warning("Large checkpoint detected: %.1fKB", size / 1024)

        return (type_prefix, serialized)

    def loads_typed(self, data: tuple[str, bytes]) -> object:
        type_str, payload = data

        if type_str == "dill":
            import dill

            return dill.loads(payload)
        elif type_str == "pickle":
            import pickle

            return pickle.loads(payload)
        raise ValueError(f"Unsupported serialization type: {type_str}")


async def create_checkpointer(
    mode: str = "sqlite",
    sqlite_db_path: str = ":memory:",
    deploy_mode: str = "LOCAL",
) -> tuple[BaseCheckpointSaver[str], Callable[[], Awaitable[None]]]:
    """Create a checkpointer based on mode and deployment configuration.

    Decision logic:
    1. mode=memory → MemorySaver (no persistence, dev/test only)
    2. Default (empty or sqlite) → AsyncSqliteSaver on persistent volume (fail-fast on error)

    Returns:
        (checkpointer, cleanup_callback) — cleanup closes underlying DB connections.

    Raises:
        ValueError: Unsupported checkpointer mode.
        ImportError: langgraph-checkpoint-sqlite not installed (sqlite mode).
        RuntimeError: SQLite initialization failed (permissions, disk, schema, etc.).
    """
    from langgraph.checkpoint.memory import MemorySaver

    forced_mode = mode.lower()

    if forced_mode and forced_mode not in {"", "memory", "sqlite"}:
        msg = (
            f"Unsupported checkpointer mode {mode!r}; "
            "supported modes: memory, sqlite (default). "
            "PostgreSQL checkpoint is not supported."
        )
        raise ValueError(msg)

    if forced_mode == "memory":
        logger.info("Checkpointer: MemorySaver (mode=memory)")
        return MemorySaver(), _noop_cleanup

    return await _create_sqlite_checkpointer(sqlite_db_path, deploy_mode=deploy_mode)


async def _create_sqlite_checkpointer(
    db_path_str: str,
    *,
    deploy_mode: str,
) -> tuple[BaseCheckpointSaver[str], Callable[[], Awaitable[None]]]:
    """Create SQLite-backed checkpointer. Raises on any failure (no silent fallback)."""
    from pathlib import Path

    try:
        import aiosqlite
        import langgraph.checkpoint.sqlite.aio  # noqa: F401  # availability probe
    except ImportError as exc:
        msg = (
            "langgraph-checkpoint-sqlite is required for SQLite checkpoint mode. "
            "Install: uv add langgraph-checkpoint-sqlite"
        )
        raise ImportError(msg) from exc

    db_path = os.path.expanduser(db_path_str)
    try:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn: aiosqlite.Connection = await aiosqlite.connect(db_path)
        from myrm_agent_harness.utils.db.sqlite import DEFAULT, harden_connection_async

        await harden_connection_async(conn, DEFAULT, db_path=Path(str(db_path)))
        try:
            saver = await _build_incremental_saver(conn)

            async def cleanup() -> None:
                await conn.close()
                logger.info("[Shutdown] SQLite connection closed")

            logger.info(
                "Checkpointer: IncrementalSessionCheckpointer[AsyncSqliteSaver] "
                "(file=%s, serde=dill, persistent, thread_registry=enabled, deploy_mode=%s)",
                db_path,
                deploy_mode,
            )
            return saver, cleanup
        except Exception:
            await conn.close()
            raise
    except Exception as exc:
        msg = f"Failed to initialize SQLite checkpointer at {db_path!r} (deploy_mode={deploy_mode})"
        raise RuntimeError(msg) from exc


async def _build_incremental_saver(
    conn: aiosqlite.Connection,
) -> BaseCheckpointSaver[str]:
    """Build IncrementalSessionCheckpointer wrapping AsyncSqliteSaver + ThreadStore."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    base_saver = AsyncSqliteSaver(conn, serde=PickleSerde())
    await base_saver.setup()

    from myrm_agent_harness.toolkits.browser.checkpoint import (
        ThreadStore,
        create_thread_tables,
    )

    await create_thread_tables(conn)
    thread_store = ThreadStore(conn)

    from langgraph.checkpoint.base import BaseCheckpointSaver

    from myrm_agent_harness.toolkits.browser import IncrementalSessionCheckpointer

    return cast(
        BaseCheckpointSaver[str],
        IncrementalSessionCheckpointer(base_saver, thread_store=thread_store),
    )


async def _noop_cleanup() -> None:
    """No-op cleanup for MemorySaver."""
    pass
