"""Hot/Cold Single-Direction Mirror Engine.

[INPUT]
- toolkits.memory.types::BaseMemory (POS: Base memory data model with L0/L1/domain fields)
- toolkits.memory.domain_types::MemoryDomain, DomainCategory (POS: Three-domain taxonomy)

[OUTPUT]
- HotColdMirrorEngine: In-process dual-tier memory cache with debounced cold SQLite mirroring.
- ColdMemoryRecord: Immutable DTO for mirrored cold records.

[POS]
Low-latency hot memory cache with single-direction asynchronous debounced sync
to SQLite cold storage. Guarantees zero cold-to-hot pollution.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite

from myrm_agent_harness.toolkits.memory.domain_types import DomainCategory, MemoryDomain
from myrm_agent_harness.toolkits.memory.types import BaseMemory

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

DEFAULT_DEBOUNCE_INTERVAL_SECONDS = 0.5
DEFAULT_MAX_DEBOUNCE_INTERVAL_SECONDS = 2.0
DEFAULT_MAX_HOT_ENTRIES = 500


@dataclass(frozen=True)
class ColdMemoryRecord:
    """Immutable representation of a cold mirrored memory item."""

    id: str
    user_id: str
    domain: str
    domain_category: str
    memory_type: str
    summary_l0: str
    overview_l1: str
    content: str
    metadata: dict[str, object]
    created_at: str
    updated_at: str


class HotColdMirrorEngine:
    """In-process hot memory cache with single-direction debounced SQLite cold mirror."""

    def __init__(
        self,
        db_path: str | Path,
        user_id: str = "default",
        *,
        debounce_interval: float = DEFAULT_DEBOUNCE_INTERVAL_SECONDS,
        max_debounce_interval: float = DEFAULT_MAX_DEBOUNCE_INTERVAL_SECONDS,
        max_hot_entries: int = DEFAULT_MAX_HOT_ENTRIES,
    ) -> None:
        self._db_path = Path(db_path).expanduser().resolve()
        self._user_id = user_id
        self._debounce_interval = max(0.01, debounce_interval)
        self._max_debounce_interval = max(self._debounce_interval, max_debounce_interval)
        self._max_hot_entries = max(1, max_hot_entries)

        self._hot_cache: dict[str, BaseMemory] = {}
        self._pending_sync: dict[str, BaseMemory] = {}
        self._first_pending_time: float | None = None
        self._debounce_task: asyncio.Task[None] | None = None
        self._connection: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
        self._closed = False

    async def initialize(self) -> None:
        """Initialize database schema and WAL mode."""
        await self._ensure_connection()

    async def _ensure_connection(self) -> aiosqlite.Connection:
        if self._connection is not None:
            return self._connection
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(str(self._db_path))
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cold_memory_mirror (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                domain TEXT NOT NULL,
                domain_category TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                summary_l0 TEXT NOT NULL DEFAULT '',
                overview_l1 TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cold_domain
            ON cold_memory_mirror(user_id, domain, domain_category)
            """
        )
        await conn.commit()
        self._connection = conn
        return conn

    def put_hot(self, memory: BaseMemory) -> None:
        """Insert or update a memory in the hot cache and trigger debounced sync."""
        if self._closed:
            raise RuntimeError("Cannot write to closed HotColdMirrorEngine")
        if len(self._hot_cache) >= self._max_hot_entries and memory.id not in self._hot_cache:
            oldest_id = next(iter(self._hot_cache))
            del self._hot_cache[oldest_id]

        try:
            now = asyncio.get_running_loop().time()
        except RuntimeError:
            now = 0.0

        if self._first_pending_time is None:
            self._first_pending_time = now

        self._hot_cache[memory.id] = memory
        self._pending_sync[memory.id] = memory
        self._schedule_debounce(now)

    def get_hot(self, memory_id: str) -> BaseMemory | None:
        """Retrieve memory directly from in-memory hot cache."""
        return self._hot_cache.get(memory_id)

    def list_hot(self, domain: MemoryDomain | None = None) -> list[BaseMemory]:
        """List hot memories, optionally filtered by domain."""
        if domain is None:
            return list(self._hot_cache.values())
        return [m for m in self._hot_cache.values() if m.domain == domain]

    def remove_hot(self, memory_id: str) -> BaseMemory | None:
        """Remove memory from hot cache."""
        return self._hot_cache.pop(memory_id, None)

    @property
    def hot_count(self) -> int:
        """Current number of items in hot cache."""
        return len(self._hot_cache)

    def _schedule_debounce(self, now: float) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return

        if (
            self._first_pending_time is not None
            and now > 0.0
            and (now - self._first_pending_time) >= self._max_debounce_interval
        ):
            if self._debounce_task is None or self._debounce_task.done():
                self._debounce_task = asyncio.create_task(self._debounce_worker(0.0))
            return

        if self._debounce_task is not None and not self._debounce_task.done():
            self._debounce_task.cancel()
        self._debounce_task = asyncio.create_task(
            self._debounce_worker(self._debounce_interval)
        )

    async def _debounce_worker(self, delay: float) -> None:
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            await self.flush()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Error in HotColdMirror debounce worker")

    async def flush(self) -> int:
        """Flush pending hot items into SQLite cold mirror immediately."""
        async with self._lock:
            if not self._pending_sync:
                self._first_pending_time = None
                return 0
            to_flush = dict(self._pending_sync)
            self._pending_sync.clear()
            self._first_pending_time = None

        conn = await self._ensure_connection()
        now_str = datetime.now(UTC).isoformat()
        records: list[tuple[str, str, str, str, str, str, str, str, str, str, str]] = []

        for mem in to_flush.values():
            mem_type = getattr(mem, "memory_type", "semantic")
            type_val = mem_type.value if hasattr(mem_type, "value") else str(mem_type)
            dom_val = mem.domain.value if hasattr(mem.domain, "value") else str(mem.domain)
            created_str = (
                mem.created_at.isoformat()
                if hasattr(mem, "created_at") and mem.created_at
                else now_str
            )
            updated_str = (
                mem.updated_at.isoformat()
                if hasattr(mem, "updated_at") and mem.updated_at
                else now_str
            )
            meta = getattr(mem, "metadata", {}) or {}
            meta_json = json.dumps(meta, default=str)

            records.append(
                (
                    mem.id,
                    self._user_id,
                    dom_val,
                    mem.domain_category,
                    type_val,
                    mem.summary_l0,
                    mem.overview_l1,
                    mem.content,
                    meta_json,
                    created_str,
                    updated_str,
                )
            )

        try:
            await conn.executemany(
                """
                INSERT INTO cold_memory_mirror (
                    id, user_id, domain, domain_category, memory_type,
                    summary_l0, overview_l1, content, metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    domain=excluded.domain,
                    domain_category=excluded.domain_category,
                    memory_type=excluded.memory_type,
                    summary_l0=excluded.summary_l0,
                    overview_l1=excluded.overview_l1,
                    content=excluded.content,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                records,
            )
            await conn.commit()
            return len(records)
        except Exception:
            async with self._lock:
                for k, v in to_flush.items():
                    if k not in self._pending_sync:
                        self._pending_sync[k] = v
                if self._first_pending_time is None and self._pending_sync:
                    with contextlib.suppress(RuntimeError):
                        self._first_pending_time = asyncio.get_running_loop().time()
            raise

    async def query_cold(
        self,
        *,
        domain: MemoryDomain | None = None,
        category: DomainCategory | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[ColdMemoryRecord]:
        """Query cold SQLite mirror directly.
<BLANK_LINE>
        STRONG ISOLATION: Cold queries never pollute or overwrite hot cache.
        """
        conn = await self._ensure_connection()
        clauses = ["user_id = ?"]
        params: list[object] = [self._user_id]

        if domain is not None:
            clauses.append("domain = ?")
            params.append(domain.value)
        if category is not None:
            clauses.append("domain_category = ?")
            params.append(category.value)

        where_sql = " AND ".join(clauses)
        params.extend([limit, offset])

        async with conn.execute(
            f"""
            SELECT id, user_id, domain, domain_category, memory_type,
                   summary_l0, overview_l1, content, metadata_json,
                   created_at, updated_at
            FROM cold_memory_mirror
            WHERE {where_sql}
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """,
            params,
        ) as cursor:
            rows = await cursor.fetchall()

        results: list[ColdMemoryRecord] = []
        for r in rows:
            meta_raw = r["metadata_json"]
            meta_dict: dict[str, object] = {}
            if meta_raw:
                with contextlib.suppress(Exception):
                    meta_dict = json.loads(meta_raw)

            results.append(
                ColdMemoryRecord(
                    id=str(r["id"]),
                    user_id=str(r["user_id"]),
                    domain=str(r["domain"]),
                    domain_category=str(r["domain_category"]),
                    memory_type=str(r["memory_type"]),
                    summary_l0=str(r["summary_l0"]),
                    overview_l1=str(r["overview_l1"]),
                    content=str(r["content"]),
                    metadata=meta_dict,
                    created_at=str(r["created_at"]),
                    updated_at=str(r["updated_at"]),
                )
            )
        return results

    async def count_cold(self, domain: MemoryDomain | None = None) -> int:
        """Count total cold mirrored records, optionally filtered by domain."""
        conn = await self._ensure_connection()
        if domain is None:
            async with conn.execute(
                "SELECT COUNT(*) FROM cold_memory_mirror WHERE user_id = ?",
                (self._user_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return int(row[0]) if row else 0

        async with conn.execute(
            "SELECT COUNT(*) FROM cold_memory_mirror WHERE user_id = ? AND domain = ?",
            (self._user_id, domain.value),
        ) as cursor:
            row = await cursor.fetchone()
            return int(row[0]) if row else 0

    async def close(self) -> None:
        """Flush any pending updates and close connection."""
        self._closed = True
        if self._debounce_task is not None and not self._debounce_task.done():
            self._debounce_task.cancel()
        await self.flush()
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def __aenter__(self) -> HotColdMirrorEngine:
        await self.initialize()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        await self.close()
