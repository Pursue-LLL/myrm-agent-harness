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
    1. mode=memory → MemorySaver (no persistence)
    2. Default → AsyncSqliteSaver (all deploy modes use SQLite on persistent volume)
    3. Fallback → MemorySaver

    Returns:
        (checkpointer, cleanup_callback) — cleanup closes underlying DB connections.
    """
    from langgraph.checkpoint.memory import MemorySaver

    forced_mode = mode.lower()

    if forced_mode == "memory":
        logger.info("Checkpointer: MemorySaver (mode=memory)")
        return MemorySaver(), _noop_cleanup

    if not forced_mode or forced_mode == "sqlite":
        result = await _try_create_sqlite(sqlite_db_path)
        if result is not None:
            return result

    logger.warning("Checkpointer: MemorySaver (fallback, deploy_mode=%s)", deploy_mode)
    return MemorySaver(), _noop_cleanup


async def _try_create_sqlite(
    db_path_str: str,
) -> tuple[BaseCheckpointSaver[str], Callable[[], Awaitable[None]]] | None:
    """Attempt to create SQLite-backed checkpointer. Returns None on failure."""
    try:
        from pathlib import Path

        import aiosqlite
        import langgraph.checkpoint.sqlite.aio  # noqa: F401  # availability probe: raises ImportError if optional dep missing

        db_path = os.path.expanduser(db_path_str)
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
                "(file=%s, serde=dill, persistent, thread_registry=enabled)",
                db_path,
            )
            return saver, cleanup
        except Exception:
            await conn.close()
            raise
    except ImportError:
        logger.warning("langgraph-checkpoint-sqlite not installed, falling back to MemorySaver")
        logger.warning("   Install: uv add langgraph-checkpoint-sqlite")
    except Exception as e:
        logger.error("SqliteSaver init failed: %s, falling back to MemorySaver", e, exc_info=True)
    return None


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
