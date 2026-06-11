"""SQLite Relational Store — zero-dependency relational backend using aiosqlite.


[INPUT]
myrm_agent_harness.toolkits.memory.relational.base (POS: Relational store abstraction layer)
myrm_agent_harness.toolkits.memory.relational.exceptions
myrm_agent_harness.toolkits.memory.types (POS: Memory type definitions)

[OUTPUT]
SQLiteRelationalStore: Async SQLite relational store with WAL mode,
                       connection reuse, and JSON column support.

[POS]
Lightweight relational store backed by aiosqlite. WAL mode + connection reuse for
high-performance async I/O. Full CRUD for Profile, Procedural, and Pending memories.
"""

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from uuid import uuid4

import aiosqlite

from myrm_agent_harness.toolkits.memory.relational._converters import (
    PROCEDURAL_COLUMNS,
    now_iso,
    parse_dt,
    row_to_pending,
    row_to_procedural,
    row_to_profile,
)
from myrm_agent_harness.toolkits.memory.relational.base import RelationalStore
from myrm_agent_harness.toolkits.memory.relational.exceptions import (
    RelationalConnectionError,
    RelationalNotFoundError,
    RelationalQueryError,
)
from myrm_agent_harness.toolkits.memory.types import (
    MemoryScope,
    PendingRecord,
    ProceduralMemory,
    ProfileAttributeSnapshot,
    ProfileEntry,
)

logger = logging.getLogger(__name__)


class SQLiteRelationalStore(RelationalStore):
    """SQLite relational store with WAL mode and connection reuse.

    Features:
    - Async I/O via aiosqlite
    - WAL mode for concurrent reads
    - Connection reuse with double-checked locking
    - JSON column support for metadata/keywords
    - Composite index optimization

    Example::

        async with SQLiteRelationalStore("~/.app/relational.db") as store:
            await store.set_profile("u1", "language", "zh")
            lang = await store.get_profile("u1", "language")
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path).expanduser().resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection: aiosqlite.Connection | None = None
        self._connection_lock = asyncio.Lock()
        self._initialized = False
        self._closed = False
        logger.info("SQLiteRelationalStore initialized: %s", self._db_path)

    async def _get_connection(self) -> aiosqlite.Connection:
        if self._closed:
            raise RelationalConnectionError("Store has been closed")
        if self._connection is None:
            async with self._connection_lock:
                if self._closed:
                    raise RelationalConnectionError("Store has been closed")
                if self._connection is None:
                    try:
                        from myrm_agent_harness.utils.db.sqlite import prepare_database_file

                        prepare_database_file(self._db_path)
                        self._connection = await aiosqlite.connect(str(self._db_path))
                        await self._init_connection_settings()
                        await self._init_tables()
                    except Exception as e:
                        raise RelationalConnectionError(f"Failed to connect: {e}") from e
        return self._connection

    async def _init_connection_settings(self) -> None:
        if self._connection is None:
            return
        from myrm_agent_harness.utils.db.sqlite import DURABLE, harden_connection_async

        await harden_connection_async(self._connection, DURABLE, db_path=self._db_path)
        await self._connection.commit()

    async def _table_exists(self, table_name: str) -> bool:
        assert self._connection is not None
        async with self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ) as cursor:
            return await cursor.fetchone() is not None

    async def _table_columns(self, table_name: str) -> set[str]:
        assert self._connection is not None
        async with self._connection.execute(f"PRAGMA table_info({table_name})") as cursor:
            rows = await cursor.fetchall()
        return {str(row[1]) for row in rows}

    async def _ensure_scope_schema(self) -> None:
        assert self._connection is not None

        if await self._table_exists("profiles"):
            profile_columns = await self._table_columns("profiles")
            if "primary_namespace" not in profile_columns:
                await self._connection.execute("ALTER TABLE profiles RENAME TO profiles_legacy")
                await self._connection.execute(
                    """
                    CREATE TABLE profiles (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        key TEXT NOT NULL,
                        value TEXT NOT NULL,
                        primary_namespace TEXT NOT NULL DEFAULT '',
                        namespaces TEXT NOT NULL DEFAULT '[]',
                        agent_id TEXT,
                        channel_id TEXT,
                        conversation_id TEXT,
                        task_id TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                """
                )
                await self._connection.execute(
                    """
                    INSERT INTO profiles (
                        id, user_id, key, value, primary_namespace, namespaces, created_at, updated_at
                    )
                    SELECT id, user_id, key, value, '', '[]', created_at, updated_at
                    FROM profiles_legacy
                """
                )
                await self._connection.execute("DROP TABLE profiles_legacy")

        if await self._table_exists("procedural_rules"):
            rule_columns = await self._table_columns("procedural_rules")
            if "primary_namespace" not in rule_columns:
                await self._connection.execute("ALTER TABLE procedural_rules RENAME TO procedural_rules_legacy")
                await self._connection.execute(
                    """
                    CREATE TABLE procedural_rules (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        content TEXT NOT NULL DEFAULT '',
                        trigger_text TEXT NOT NULL,
                        action_text TEXT NOT NULL,
                        priority INTEGER NOT NULL DEFAULT 0,
                        is_active INTEGER NOT NULL DEFAULT 1,
                        trigger_keywords TEXT,
                        source TEXT NOT NULL DEFAULT 'user_extracted',
                        metadata TEXT,
                        primary_namespace TEXT NOT NULL DEFAULT '',
                        namespaces TEXT NOT NULL DEFAULT '[]',
                        agent_id TEXT,
                        channel_id TEXT,
                        conversation_id TEXT,
                        task_id TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                """
                )
                await self._connection.execute(
                    """
                    INSERT INTO procedural_rules (
                        id, user_id, content, trigger_text, action_text, priority, is_active,
                        trigger_keywords, source, metadata, primary_namespace, namespaces,
                        created_at, updated_at
                    )
                    SELECT id, user_id, content, trigger_text, action_text, priority, is_active,
                           trigger_keywords, source, metadata, '', '[]', created_at, updated_at
                    FROM procedural_rules_legacy
                """
                )
                await self._connection.execute("DROP TABLE procedural_rules_legacy")

        if await self._table_exists("procedural_rules"):
            rule_columns = await self._table_columns("procedural_rules")
            if "tool_name" not in rule_columns:
                await self._connection.execute("ALTER TABLE procedural_rules ADD COLUMN tool_name TEXT")
            if "tool_rule_priority" not in rule_columns:
                await self._connection.execute(
                    "ALTER TABLE procedural_rules ADD COLUMN tool_rule_priority TEXT NOT NULL DEFAULT 'normal'"
                )
            if "access_count" not in rule_columns:
                await self._connection.execute(
                    "ALTER TABLE procedural_rules ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0"
                )
            if "last_accessed_at" not in rule_columns:
                await self._connection.execute(
                    "ALTER TABLE procedural_rules ADD COLUMN last_accessed_at TEXT"
                )

    def _scope_values(
        self, scope: MemoryScope | None
    ) -> tuple[str, str, str | None, str | None, str | None, str | None]:
        if scope is None:
            return "", "[]", None, None, None, None
        return (
            scope.primary_namespace,
            json.dumps(scope.namespaces),
            scope.agent_id,
            scope.channel_id,
            scope.conversation_id,
            scope.task_id,
        )

    def _scope_filter_sql(self, namespaces: list[str] | None) -> tuple[str, list[str]]:
        if not namespaces:
            return "", []
        placeholders = ",".join("?" for _ in namespaces)
        return f" AND primary_namespace IN ({placeholders})", list(namespaces)

    async def _init_tables(self) -> None:
        if self._initialized or self._connection is None:
            return
        try:
            await self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    primary_namespace TEXT NOT NULL DEFAULT '',
                    namespaces TEXT NOT NULL DEFAULT '[]',
                    agent_id TEXT,
                    channel_id TEXT,
                    conversation_id TEXT,
                    task_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """
            )
            await self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS procedural_rules (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    trigger_text TEXT NOT NULL,
                    action_text TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 0,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    trigger_keywords TEXT,
                    source TEXT NOT NULL DEFAULT 'user_extracted',
                    metadata TEXT,
                    primary_namespace TEXT NOT NULL DEFAULT '',
                    namespaces TEXT NOT NULL DEFAULT '[]',
                    agent_id TEXT,
                    channel_id TEXT,
                    conversation_id TEXT,
                    task_id TEXT,
                    tool_name TEXT,
                    tool_rule_priority TEXT NOT NULL DEFAULT 'normal',
                    access_count INTEGER NOT NULL DEFAULT 0,
                    last_accessed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """
            )
            await self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_records (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    memory_data TEXT,
                    source_chat_id TEXT,
                    source_message_id TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                )
            """
            )
            await self._ensure_scope_schema()
            for idx_sql in (
                "CREATE INDEX IF NOT EXISTS idx_profiles_user ON profiles(user_id)",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_profiles_user_key_scope ON profiles(user_id, key, primary_namespace)",
                "CREATE INDEX IF NOT EXISTS idx_profiles_user_scope ON profiles(user_id, primary_namespace)",
                "CREATE INDEX IF NOT EXISTS idx_rules_user ON procedural_rules(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_rules_user_active ON procedural_rules(user_id, is_active)",
                "CREATE INDEX IF NOT EXISTS idx_rules_user_scope ON procedural_rules(user_id, primary_namespace)",
                "CREATE INDEX IF NOT EXISTS idx_rules_tool_name ON procedural_rules(tool_name) WHERE tool_name IS NOT NULL",
                "CREATE INDEX IF NOT EXISTS idx_pending_user ON pending_records(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_pending_user_status ON pending_records(user_id, status)",
            ):
                await self._connection.execute(idx_sql)
            await self._connection.commit()
            self._initialized = True
        except Exception as e:
            raise RelationalConnectionError(f"Failed to initialize tables: {e}") from e

    # ── Profile ──────────────────────────────────────────────────────

    async def get_profile(self, key: str, *, namespaces: list[str] | None = None) -> str | None:
        conn = await self._get_connection()
        scope_sql, scope_params = self._scope_filter_sql(namespaces)
        try:
            async with conn.execute(
                f"SELECT value FROM profiles WHERE key = ?{scope_sql} ORDER BY updated_at DESC LIMIT 1",
                (key, *scope_params),
            ) as cursor:
                row = await cursor.fetchone()
            return row[0] if row else None
        except Exception as e:
            raise RelationalQueryError(f"get_profile failed: {e}") from e

    async def get_profile_snapshot(self, key: str, *, namespaces: list[str] | None = None) -> ProfileAttributeSnapshot:
        conn = await self._get_connection()
        scope_sql, scope_params = self._scope_filter_sql(namespaces)
        try:
            async with conn.execute(
                f"""SELECT key, value, updated_at
                    FROM profiles
                    WHERE key = ?{scope_sql}
                    ORDER BY updated_at DESC
                    LIMIT 1""",
                (key, *scope_params),
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                return ProfileAttributeSnapshot(key=key, exists=False, revision=f"missing:{key}")
            value = str(row[1])
            updated_at = parse_dt(str(row[2]))
            revision = _profile_revision(str(row[0]), value, updated_at.isoformat())
            return ProfileAttributeSnapshot(
                key=str(row[0]),
                value=value,
                exists=True,
                revision=revision,
                updated_at=updated_at,
            )
        except Exception as e:
            raise RelationalQueryError(f"get_profile_snapshot failed: {e}") from e

    async def set_profile(self, key: str, value: str, *, scope: MemoryScope | None = None) -> None:
        conn = await self._get_connection()
        now = now_iso()
        (
            primary_namespace,
            namespaces_json,
            agent_id,
            channel_id,
            conversation_id,
            task_id,
        ) = self._scope_values(scope)
        try:
            await conn.execute(
                """INSERT INTO profiles (
                       id, user_id, key, value, primary_namespace, namespaces, agent_id,
                       channel_id, conversation_id, task_id, created_at, updated_at
                   )
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, key, primary_namespace) DO UPDATE SET
                       value = excluded.value,
                       namespaces = excluded.namespaces,
                       agent_id = excluded.agent_id,
                       channel_id = excluded.channel_id,
                       conversation_id = excluded.conversation_id,
                       task_id = excluded.task_id,
                       updated_at = excluded.updated_at""",
                (
                    str(uuid4()),
                    "default",
                    key,
                    value,
                    primary_namespace,
                    namespaces_json,
                    agent_id,
                    channel_id,
                    conversation_id,
                    task_id,
                    now,
                    now,
                ),
            )
            await conn.commit()
        except Exception as e:
            raise RelationalQueryError(f"set_profile failed: {e}") from e

    async def delete_profile(self, key: str, *, namespaces: list[str] | None = None) -> bool:
        conn = await self._get_connection()
        scope_sql, scope_params = self._scope_filter_sql(namespaces)
        try:
            cursor = await conn.execute(
                f"DELETE FROM profiles WHERE (key = ? OR id = ?){scope_sql}",
                (key, key, *scope_params),
            )
            await conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            raise RelationalQueryError(f"delete_profile failed: {e}") from e

    async def list_profiles(
        self, *, limit: int = 1000, offset: int = 0, namespaces: list[str] | None = None
    ) -> list[ProfileEntry]:
        conn = await self._get_connection()
        scope_sql, scope_params = self._scope_filter_sql(namespaces)
        try:
            async with conn.execute(
                """SELECT id, user_id, key, value, primary_namespace, namespaces, agent_id,
                          channel_id, conversation_id, task_id, created_at, updated_at
                   FROM profiles
                   WHERE 1=1
                     AND substr(key, 1, 8) != '_system_'"""
                + scope_sql
                + " ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (*scope_params, limit, offset),
            ) as cursor:
                rows = await cursor.fetchall()
            return [row_to_profile(r) for r in rows]
        except Exception as e:
            raise RelationalQueryError(f"list_profiles failed: {e}") from e

    async def count_profiles(self, *, namespaces: list[str] | None = None) -> int:
        conn = await self._get_connection()
        scope_sql, scope_params = self._scope_filter_sql(namespaces)
        try:
            async with conn.execute(
                f"SELECT COUNT(*) FROM profiles WHERE 1=1 AND substr(key, 1, 8) != '_system_' {scope_sql}",
                scope_params,
            ) as cursor:
                row = await cursor.fetchone()
            return row[0] if row else 0
        except Exception as e:
            raise RelationalQueryError(f"count_profiles failed: {e}") from e

    # ── Procedural rules ─────────────────────────────────────────────

    async def create_rule(self, rule: ProceduralMemory) -> ProceduralMemory:
        conn = await self._get_connection()
        rule_id = rule.id or str(uuid4())
        now = now_iso()
        (
            primary_namespace,
            namespaces_json,
            agent_id,
            channel_id,
            conversation_id,
            task_id,
        ) = self._scope_values(rule.scope)
        try:
            await conn.execute(
                """INSERT INTO procedural_rules
                   (id, user_id, content, trigger_text, action_text, priority, is_active, trigger_keywords,
                    source, metadata, primary_namespace, namespaces, agent_id, channel_id, conversation_id,
                    task_id, tool_name, tool_rule_priority, access_count, last_accessed_at,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    rule_id,
                    "default",
                    rule.content,
                    rule.trigger,
                    rule.action,
                    rule.priority,
                    int(rule.is_active),
                    json.dumps(rule.trigger_keywords),
                    rule.source.value,
                    json.dumps(dict(rule.metadata)) if rule.metadata else None,
                    primary_namespace,
                    namespaces_json,
                    agent_id,
                    channel_id,
                    conversation_id,
                    task_id,
                    rule.tool_name,
                    rule.tool_rule_priority.value,
                    rule.access_count,
                    rule.last_accessed_at.isoformat() if rule.last_accessed_at else None,
                    now,
                    now,
                ),
            )
            await conn.commit()
            rule.id = rule_id
            return rule
        except Exception as e:
            raise RelationalQueryError(f"create_rule failed: {e}") from e

    async def get_rule(self, rule_id: str, *, namespaces: list[str] | None = None) -> ProceduralMemory | None:
        conn = await self._get_connection()
        scope_sql, scope_params = self._scope_filter_sql(namespaces)
        try:
            async with conn.execute(
                f"SELECT {PROCEDURAL_COLUMNS} FROM procedural_rules WHERE id = ?{scope_sql}",
                (rule_id, *scope_params),
            ) as cursor:
                row = await cursor.fetchone()
            return row_to_procedural(row) if row else None
        except Exception as e:
            raise RelationalQueryError(f"get_rule failed: {e}") from e

    async def search_rules(
        self, query: str, *, limit: int = 10, namespaces: list[str] | None = None
    ) -> list[ProceduralMemory]:
        conn = await self._get_connection()
        pattern = f"%{query}%"
        scope_sql, scope_params = self._scope_filter_sql(namespaces)
        try:
            async with conn.execute(
                f"""SELECT {PROCEDURAL_COLUMNS} FROM procedural_rules
                   WHERE is_active = 1
                     AND (trigger_text LIKE ? OR action_text LIKE ?)
                """
                + scope_sql
                + " ORDER BY priority DESC LIMIT ?",
                (pattern, pattern, *scope_params, limit),
            ) as cursor:
                rows = await cursor.fetchall()
            return [row_to_procedural(r) for r in rows]
        except Exception as e:
            raise RelationalQueryError(f"search_rules failed: {e}") from e

    async def list_rules(
        self,
        *,
        active_only: bool = True,
        limit: int = 1000,
        offset: int = 0,
        namespaces: list[str] | None = None,
    ) -> list[ProceduralMemory]:
        conn = await self._get_connection()
        scope_sql, scope_params = self._scope_filter_sql(namespaces)
        try:
            if active_only:
                sql = (
                    f"SELECT {PROCEDURAL_COLUMNS} FROM procedural_rules WHERE is_active = 1"
                    + scope_sql
                    + " ORDER BY priority DESC LIMIT ? OFFSET ?"
                )
                params: tuple[str | int, ...] = (*scope_params, limit, offset)
            else:
                sql = (
                    f"SELECT {PROCEDURAL_COLUMNS} FROM procedural_rules WHERE 1=1"
                    + scope_sql
                    + " ORDER BY priority DESC LIMIT ? OFFSET ?"
                )
                params = (*scope_params, limit, offset)
            async with conn.execute(sql, params) as cursor:
                rows = await cursor.fetchall()
            return [row_to_procedural(r) for r in rows]
        except Exception as e:
            raise RelationalQueryError(f"list_rules failed: {e}") from e

    async def count_rules(self, *, active_only: bool = True, namespaces: list[str] | None = None) -> int:
        conn = await self._get_connection()
        scope_sql, scope_params = self._scope_filter_sql(namespaces)
        try:
            if active_only:
                sql = f"SELECT COUNT(*) FROM procedural_rules WHERE is_active = 1{scope_sql}"
            else:
                sql = f"SELECT COUNT(*) FROM procedural_rules WHERE 1=1 {scope_sql}"

            async with conn.execute(sql, scope_params) as cursor:
                row = await cursor.fetchone()
            return row[0] if row else 0
        except Exception as e:
            raise RelationalQueryError(f"count_rules failed: {e}") from e

    async def list_rules_by_tool(
        self,
        tool_name: str,
        *,
        active_only: bool = True,
        limit: int = 30,
        namespaces: list[str] | None = None,
    ) -> list[ProceduralMemory]:
        conn = await self._get_connection()
        scope_sql, scope_params = self._scope_filter_sql(namespaces)
        try:
            base = f"SELECT {PROCEDURAL_COLUMNS} FROM procedural_rules WHERE tool_name = ?"
            if active_only:
                base += " AND is_active = 1"
            sql = base + scope_sql + " ORDER BY priority DESC LIMIT ?"
            params: tuple[str | int, ...] = (tool_name, *scope_params, limit)
            async with conn.execute(sql, params) as cursor:
                rows = await cursor.fetchall()
            return [row_to_procedural(r) for r in rows]
        except Exception as e:
            raise RelationalQueryError(f"list_rules_by_tool failed: {e}") from e

    async def update_rule(self, rule_id: str, rule: ProceduralMemory) -> ProceduralMemory:
        conn = await self._get_connection()
        now = now_iso()
        try:
            cursor = await conn.execute(
                """UPDATE procedural_rules
                   SET content = ?, trigger_text = ?, action_text = ?, priority = ?,
                       is_active = ?, trigger_keywords = ?, source = ?, metadata = ?,
                       primary_namespace = ?, namespaces = ?, agent_id = ?, channel_id = ?,
                       conversation_id = ?, task_id = ?, tool_name = ?,
                       tool_rule_priority = ?, access_count = ?, last_accessed_at = ?,
                       updated_at = ?
                   WHERE id = ?""",
                (
                    rule.content,
                    rule.trigger,
                    rule.action,
                    rule.priority,
                    int(rule.is_active),
                    json.dumps(rule.trigger_keywords),
                    rule.source.value,
                    json.dumps(dict(rule.metadata)) if rule.metadata else None,
                    rule.scope.primary_namespace,
                    json.dumps(rule.scope.namespaces),
                    rule.scope.agent_id,
                    rule.scope.channel_id,
                    rule.scope.conversation_id,
                    rule.scope.task_id,
                    rule.tool_name,
                    rule.tool_rule_priority.value,
                    rule.access_count,
                    rule.last_accessed_at.isoformat() if rule.last_accessed_at else None,
                    now,
                    rule_id,
                ),
            )
            await conn.commit()
            if cursor.rowcount == 0:
                raise RelationalNotFoundError(f"Rule {rule_id} not found")
            rule.id = rule_id
            return rule
        except RelationalNotFoundError:
            raise
        except Exception as e:
            raise RelationalQueryError(f"update_rule failed: {e}") from e

    async def delete_rule(self, rule_id: str) -> bool:
        conn = await self._get_connection()
        try:
            cursor = await conn.execute("DELETE FROM procedural_rules WHERE id = ?", (rule_id,))
            await conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            raise RelationalQueryError(f"delete_rule failed: {e}") from e

    async def delete_all(self) -> int:
        conn = await self._get_connection()
        try:
            c1 = await conn.execute("DELETE FROM profiles", ())
            c2 = await conn.execute("DELETE FROM procedural_rules", ())
            c3 = await conn.execute("DELETE FROM pending_records", ())
            await conn.commit()
            return (c1.rowcount or 0) + (c2.rowcount or 0) + (c3.rowcount or 0)
        except Exception as e:
            raise RelationalQueryError(f"delete_all failed: {e}") from e

    # ── Pending (approval queue) ─────────────────────────────────────

    async def submit_pending(self, record: PendingRecord) -> str:
        conn = await self._get_connection()
        now = now_iso()
        try:
            await conn.execute(
                """INSERT INTO pending_records
                   (id, user_id, memory_type, content, memory_data, source_chat_id, source_message_id, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (
                    record.id,
                    "default",
                    record.memory_type.value,
                    record.content,
                    json.dumps(record.memory_data),
                    record.source_chat_id,
                    record.source_message_id,
                    now,
                ),
            )
            await conn.commit()
            return record.id
        except Exception as e:
            raise RelationalQueryError(f"submit_pending failed: {e}") from e

    async def get_pending(self, pending_id: str) -> PendingRecord | None:
        conn = await self._get_connection()
        try:
            async with conn.execute("SELECT * FROM pending_records WHERE id = ?", (pending_id,)) as cursor:
                row = await cursor.fetchone()
            return row_to_pending(row) if row else None
        except Exception as e:
            raise RelationalQueryError(f"get_pending failed: {e}") from e

    async def pending_exists(self, memory_type: str, content: str) -> bool:
        conn = await self._get_connection()
        try:
            async with conn.execute(
                "SELECT 1 FROM pending_records WHERE memory_type = ? AND content = ? AND status = 'pending' LIMIT 1",
                (memory_type, content),
            ) as cursor:
                return await cursor.fetchone() is not None
        except Exception as e:
            raise RelationalQueryError(f"pending_exists failed: {e}") from e

    async def mark_pending(self, pending_id: str, status: str) -> None:
        conn = await self._get_connection()
        now = now_iso()
        try:
            await conn.execute(
                "UPDATE pending_records SET status = ?, resolved_at = ? WHERE id = ?",
                (status, now, pending_id),
            )
            await conn.commit()
        except Exception as e:
            raise RelationalQueryError(f"mark_pending failed: {e}") from e

    async def list_pending(self, *, limit: int = 50) -> list[PendingRecord]:
        conn = await self._get_connection()
        try:
            async with conn.execute(
                "SELECT * FROM pending_records WHERE status = 'pending' ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
            return [row_to_pending(r) for r in rows]
        except Exception as e:
            raise RelationalQueryError(f"list_pending failed: {e}") from e

    async def count_pending(self) -> int:
        conn = await self._get_connection()
        try:
            async with conn.execute("SELECT COUNT(*) FROM pending_records WHERE status = 'pending'", ()) as cursor:
                row = await cursor.fetchone()
            return row[0] if row else 0
        except Exception as e:
            raise RelationalQueryError(f"count_pending failed: {e}") from e

    async def batch_mark_pending(self, pending_ids: list[str], status: str) -> int:
        if not pending_ids:
            return 0
        conn = await self._get_connection()
        now = now_iso()
        try:
            placeholders = ",".join("?" for _ in pending_ids)
            cursor = await conn.execute(
                f"UPDATE pending_records SET status = ?, resolved_at = ? WHERE id IN ({placeholders}) AND status = 'pending'",
                [status, now, *pending_ids],
            )
            await conn.commit()
            return cursor.rowcount or 0
        except Exception as e:
            raise RelationalQueryError(f"batch_mark_pending failed: {e}") from e

    # ── Lifecycle ────────────────────────────────────────────────────

    async def close(self) -> None:
        self._closed = True
        if self._connection is not None:
            from myrm_agent_harness.utils.db.sqlite import checkpoint_truncate_async

            await checkpoint_truncate_async(self._connection)
            await self._connection.close()
            self._connection = None
            logger.info("SQLiteRelationalStore closed")


def _profile_revision(key: str, value: str, updated_at: str) -> str:
    payload = "\x00".join((key, value, updated_at))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
