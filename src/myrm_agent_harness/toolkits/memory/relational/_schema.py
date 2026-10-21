"""SQLite relational schema bootstrap: table DDL, legacy scope-column migration and indexes.

[INPUT]
- memory.relational._exact_fact_store::init_exact_fact_tables (POS: exact-fact FTS5 table bootstrap)
- Third-party: aiosqlite

[OUTPUT]
- init_relational_schema: Create or migrate the profile, procedural-rule and pending tables with their
  indexes and the exact-fact tables; returns whether FTS5 is supported.

[POS]
Schema bootstrap for SQLiteRelationalStore. Stateless: every function operates on the given connection.
"""

import aiosqlite

from myrm_agent_harness.toolkits.memory.relational._exact_fact_store import init_exact_fact_tables


async def _table_exists(conn: aiosqlite.Connection, table_name: str) -> bool:
    async with conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ) as cursor:
        return await cursor.fetchone() is not None


async def _table_columns(conn: aiosqlite.Connection, table_name: str) -> set[str]:
    async with conn.execute(f"PRAGMA table_info({table_name})") as cursor:
        rows = list(await cursor.fetchall())
    return {str(row[1]) for row in rows}


async def _ensure_scope_schema(conn: aiosqlite.Connection) -> None:
    if await _table_exists(conn, "profiles"):
        profile_columns = await _table_columns(conn, "profiles")
        if "primary_namespace" not in profile_columns:
            await conn.execute("ALTER TABLE profiles RENAME TO profiles_legacy")
            await conn.execute(
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
            await conn.execute(
                """
                INSERT INTO profiles (
                    id, user_id, key, value, primary_namespace, namespaces, created_at, updated_at
                )
                SELECT id, user_id, key, value, '', '[]', created_at, updated_at
                FROM profiles_legacy
            """
            )
            await conn.execute("DROP TABLE profiles_legacy")

    if await _table_exists(conn, "procedural_rules"):
        rule_columns = await _table_columns(conn, "procedural_rules")
        if "primary_namespace" not in rule_columns:
            await conn.execute("ALTER TABLE procedural_rules RENAME TO procedural_rules_legacy")
            await conn.execute(
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
            await conn.execute(
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
            await conn.execute("DROP TABLE procedural_rules_legacy")

    if await _table_exists(conn, "procedural_rules"):
        rule_columns = await _table_columns(conn, "procedural_rules")
        if "tool_name" not in rule_columns:
            await conn.execute("ALTER TABLE procedural_rules ADD COLUMN tool_name TEXT")
        if "tool_rule_priority" not in rule_columns:
            await conn.execute(
                "ALTER TABLE procedural_rules ADD COLUMN tool_rule_priority TEXT NOT NULL DEFAULT 'normal'"
            )
        if "access_count" not in rule_columns:
            await conn.execute("ALTER TABLE procedural_rules ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0")
        if "last_accessed_at" not in rule_columns:
            await conn.execute("ALTER TABLE procedural_rules ADD COLUMN last_accessed_at TEXT")
        if "is_user_locked" not in rule_columns:
            await conn.execute("ALTER TABLE procedural_rules ADD COLUMN is_user_locked INTEGER NOT NULL DEFAULT 0")
        if "expected_valid_days" not in rule_columns:
            await conn.execute("ALTER TABLE procedural_rules ADD COLUMN expected_valid_days INTEGER")

    if await _table_exists(conn, "pending_records"):
        pending_columns = await _table_columns(conn, "pending_records")
        if "resolution_action" not in pending_columns:
            await conn.execute("ALTER TABLE pending_records ADD COLUMN resolution_action TEXT NOT NULL DEFAULT 'store'")
        if "target_memory_id" not in pending_columns:
            await conn.execute("ALTER TABLE pending_records ADD COLUMN target_memory_id TEXT")
        if "target_content" not in pending_columns:
            await conn.execute("ALTER TABLE pending_records ADD COLUMN target_content TEXT")


async def init_relational_schema(conn: aiosqlite.Connection) -> bool:
    """Create or migrate every relational table and index; return whether FTS5 is supported."""
    await conn.execute(
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
    await conn.execute(
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
            updated_at TEXT NOT NULL,
            is_user_locked INTEGER NOT NULL DEFAULT 0,
            expected_valid_days INTEGER
        )
    """
    )
    await conn.execute(
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
            resolved_at TEXT,
            resolution_action TEXT NOT NULL DEFAULT 'store',
            target_memory_id TEXT,
            target_content TEXT
        )
    """
    )
    await _ensure_scope_schema(conn)
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
        "CREATE INDEX IF NOT EXISTS idx_pending_source_chat ON pending_records(source_chat_id) WHERE source_chat_id IS NOT NULL",
    ):
        await conn.execute(idx_sql)
    fts5_supported = await init_exact_fact_tables(conn)
    await conn.commit()
    return fts5_supported
