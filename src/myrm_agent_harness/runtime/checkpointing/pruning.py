"""SQLite checkpointer that can drop superseded checkpoint history and hand the space back to the filesystem.

[INPUT]
- langgraph.checkpoint.sqlite.aio::AsyncSqliteSaver (POS: upstream async SQLite saver; prune is left unimplemented)
- aiosqlite connection owned and hardened by the factory

[OUTPUT]
- PruningAsyncSqliteSaver: AsyncSqliteSaver + `aprune(thread_ids, strategy=...)` + `alist_prunable_thread_ids()`
- HistoryPrunable: structural type of a saver that offers the pair above
- prune_checkpoint_history(): prune every thread that has history, for any saver; a no-op for savers that cannot

[POS]
LangGraph writes one full-state checkpoint per step and never removes the earlier ones, yet every reader in the
product (resume, fork, session continuity) loads only the latest checkpoint of a thread, so the history is dead
weight that grows without bound. `keep_latest` — the upstream contract of `aprune` — keeps the newest checkpoint
of each (thread, namespace) together with its pending writes and deletes the rest.

The product uses no `DeltaChannel` (a channel type that rebuilds its value by walking older checkpoints), which is
what would make dropping ancestors unsafe; an architecture test keeps it that way.

Every saver call serializes on `self.lock`, so deletion runs in byte-bounded batches that each release the lock:
one conversation's multi-hundred-megabyte history must never stall the checkpoint writes of all the others.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

if TYPE_CHECKING:
    import aiosqlite
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.checkpoint.serde.base import SerializerProtocol

logger = logging.getLogger(__name__)

_KEEP_LATEST = "keep_latest"
_DELETE = "delete"

# Stored payload one deletion transaction may free, and the row cap for histories of tiny checkpoints. Checkpoint
# writers queue behind each batch, so batches stay small: pruning a synthetic 3.4 GB database under concurrent
# writers kept their 99th-percentile write latency near 250 ms, where 16 MiB batches reached 500 ms.
_BATCH_BYTES = 4 * 1024 * 1024
_BATCH_ROWS = 256
# Pause between batches so a long prune leaves the disk to everything else.
_BATCH_PAUSE_SECONDS = 0.02

# VACUUM rewrites all live data while holding the saver lock (about 20 ms per MiB of live data on a loaded machine),
# so it only runs when it hands back a lot of space and the live data is small enough to rewrite in seconds.
_VACUUM_MIN_FREE_BYTES = 64 * 1024 * 1024
_VACUUM_MIN_FREE_RATIO = 0.25
_VACUUM_MAX_LIVE_BYTES = 256 * 1024 * 1024

# Threads holding at least one checkpoint that a newer one of the same namespace replaced.
_PRUNABLE_THREADS_SQL = """
SELECT DISTINCT thread_id FROM (
    SELECT thread_id FROM checkpoints GROUP BY thread_id, checkpoint_ns HAVING COUNT(*) > 1
)
"""

# Checkpoints a newer one of the same (thread, namespace) replaced, oldest first, with the payload deleting each
# one frees. The newest checkpoint of a namespace is never listed, so it is never deleted.
_SUPERSEDED_SQL = """
SELECT c.checkpoint_ns, c.checkpoint_id,
       COALESCE(LENGTH(c.checkpoint), 0) + COALESCE(LENGTH(c.metadata), 0) + COALESCE((
           SELECT SUM(LENGTH(w.value)) FROM writes AS w
            WHERE w.thread_id = c.thread_id AND w.checkpoint_ns = c.checkpoint_ns
              AND w.checkpoint_id = c.checkpoint_id), 0)
  FROM checkpoints AS c
 WHERE c.thread_id = ?
   AND c.checkpoint_id < (
       SELECT MAX(n.checkpoint_id) FROM checkpoints AS n
        WHERE n.thread_id = c.thread_id AND n.checkpoint_ns = c.checkpoint_ns)
 ORDER BY c.checkpoint_ns, c.checkpoint_id
 LIMIT ?
"""

# Deletion is bounded above by the newest listed id and, independently, by the current newest checkpoint of the
# namespace: even a stale listing cannot delete the checkpoint a run resumes from. Writes recorded for a checkpoint
# that has not landed yet carry a newer id and are kept.
_DELETE_SUPERSEDED_SQL = """
DELETE FROM {table}
 WHERE thread_id = :thread_id AND checkpoint_ns = :namespace AND checkpoint_id <= :newest
   AND checkpoint_id < (SELECT MAX(checkpoint_id) FROM checkpoints
                         WHERE thread_id = :thread_id AND checkpoint_ns = :namespace)
"""

_Superseded = tuple[str, str, int]


@runtime_checkable
class HistoryPrunable(Protocol):
    """A saver that can name the threads with superseded history and prune them."""

    async def alist_prunable_thread_ids(self) -> list[str]: ...

    async def aprune(self, thread_ids: Sequence[str], *, strategy: str = ...) -> None: ...


@dataclass(slots=True)
class _Pruned:
    checkpoints: int = 0
    writes: int = 0
    payload_bytes: int = 0


def _take_within_budget(rows: Sequence[_Superseded], budget_bytes: int) -> list[_Superseded]:
    """The oldest rows whose payload fits the budget; at least one row so every batch makes progress."""
    taken: list[_Superseded] = []
    used = 0
    for row in rows:
        if taken and used + row[2] > budget_bytes:
            break
        taken.append(row)
        used += row[2]
    return taken


class PruningAsyncSqliteSaver(AsyncSqliteSaver):
    """`AsyncSqliteSaver` that implements the upstream `aprune` contract for the SQLite schema."""

    def __init__(
        self,
        conn: aiosqlite.Connection,
        *,
        serde: SerializerProtocol | None = None,
        batch_bytes: int = _BATCH_BYTES,
    ) -> None:
        super().__init__(conn, serde=serde)
        self._batch_bytes = batch_bytes

    async def alist_prunable_thread_ids(self) -> list[str]:
        """Threads that hold at least one superseded checkpoint, i.e. those `aprune` would shrink."""
        await self.setup()
        async with self.lock, self.conn.execute(_PRUNABLE_THREADS_SQL) as cur:
            return [str(row[0]) async for row in cur]

    async def aprune(self, thread_ids: Sequence[str], *, strategy: str = _KEEP_LATEST) -> None:
        """Prune the given threads (`keep_latest`: drop superseded checkpoints, `delete`: drop whole threads).

        Space freed here or earlier (deleted chats included) is returned to the filesystem when it is worth a VACUUM.
        """
        if strategy not in (_KEEP_LATEST, _DELETE):
            raise ValueError(f"Unsupported prune strategy {strategy!r}; expected '{_KEEP_LATEST}' or '{_DELETE}'")
        await self.setup()
        started = time.perf_counter()
        pruned = _Pruned()
        for thread_id in thread_ids:
            if strategy == _DELETE:
                await self.adelete_thread(thread_id)
            else:
                await self._prune_thread(str(thread_id), pruned)
        reclaimed_bytes = await self._reclaim_free_space()
        logger.log(
            logging.INFO if pruned.checkpoints or reclaimed_bytes else logging.DEBUG,
            "Checkpoint history pruned: strategy=%s threads=%d checkpoints=%d writes=%d payload=%.1fMiB "
            "reclaimed=%.1fMiB elapsed=%.1fs",
            strategy,
            len(thread_ids),
            pruned.checkpoints,
            pruned.writes,
            pruned.payload_bytes / 2**20,
            reclaimed_bytes / 2**20,
            time.perf_counter() - started,
        )

    async def _prune_thread(self, thread_id: str, pruned: _Pruned) -> None:
        while batch := await self._prune_batch(thread_id):
            pruned.checkpoints += batch.checkpoints
            pruned.writes += batch.writes
            pruned.payload_bytes += batch.payload_bytes
            await asyncio.sleep(_BATCH_PAUSE_SECONDS)

    async def _prune_batch(self, thread_id: str) -> _Pruned | None:
        """Delete one budget-sized batch of the thread's oldest superseded checkpoints; None when none are left."""
        async with self.lock:
            try:
                async with self.conn.execute(_SUPERSEDED_SQL, (thread_id, _BATCH_ROWS)) as cur:
                    listed = [(str(ns), str(cid), int(size)) for ns, cid, size in await cur.fetchall()]
                batch = _take_within_budget(listed, self._batch_bytes)
                # Rows are ordered by id within a namespace, so the last one of each is its newest.
                newest_per_namespace = {namespace: checkpoint_id for namespace, checkpoint_id, _ in batch}
                pruned = _Pruned(payload_bytes=sum(size for _, _, size in batch))
                for namespace, newest in newest_per_namespace.items():
                    params = {"thread_id": thread_id, "namespace": namespace, "newest": newest}
                    async with self.conn.execute(_DELETE_SUPERSEDED_SQL.format(table="writes"), params) as cur:
                        pruned.writes += cur.rowcount
                    async with self.conn.execute(_DELETE_SUPERSEDED_SQL.format(table="checkpoints"), params) as cur:
                        pruned.checkpoints += cur.rowcount
                await self.conn.commit()
            except BaseException:
                # A cancelled batch must not leave a half-done transaction for the next saver call to commit.
                await asyncio.shield(self.conn.rollback())
                raise
        return pruned if pruned.checkpoints else None

    async def _reclaim_free_space(self) -> int:
        """VACUUM when enough space is free to be worth rewriting the live data; returns the bytes the file shrank."""
        async with self.lock:
            database = await self._database_file()
            if database is None:
                return 0
            page_size, page_count, free_pages = await self._page_accounting()
            free_bytes = page_size * free_pages
            live_bytes = page_size * (page_count - free_pages)
            worthwhile = (
                free_bytes >= _VACUUM_MIN_FREE_BYTES
                and free_bytes >= (free_bytes + live_bytes) * _VACUUM_MIN_FREE_RATIO
                and live_bytes <= _VACUUM_MAX_LIVE_BYTES
                # The rebuilt copy and the WAL it travels through each need room for the live data.
                and shutil.disk_usage(database.parent).free >= live_bytes * 2
            )
            if not worthwhile:
                return 0
            size_before = database.stat().st_size
            try:
                await self.conn.execute("VACUUM")
                async with self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)"):
                    pass
            except Exception:
                logger.warning("Checkpoint database VACUUM failed; freed pages stay reusable", exc_info=True)
                return 0
            return max(0, size_before - database.stat().st_size)

    async def _database_file(self) -> Path | None:
        """Path of the main database file; None for an in-memory database."""
        async with self.conn.execute("PRAGMA database_list") as cur:
            for _, name, file in await cur.fetchall():
                if name == "main" and file:
                    return Path(file)
        return None

    async def _page_accounting(self) -> tuple[int, int, int]:
        """(page size, page count, free page count) of the main database."""
        values: list[int] = []
        for pragma in ("page_size", "page_count", "freelist_count"):
            async with self.conn.execute(f"PRAGMA {pragma}") as cur:
                row = await cur.fetchone()
            values.append(int(row[0]) if row else 0)
        return values[0], values[1], values[2]


async def prune_checkpoint_history(checkpointer: BaseCheckpointSaver[str]) -> bool:
    """Drop the superseded history of every thread that has some; False for a checkpointer that cannot prune."""
    if not isinstance(checkpointer, HistoryPrunable):
        return False
    try:
        thread_ids = await checkpointer.alist_prunable_thread_ids()
    except NotImplementedError:
        return False
    await checkpointer.aprune(thread_ids, strategy=_KEEP_LATEST)
    return True
