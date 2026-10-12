"""SQLiteRelationalStore schema upgrades — legacy databases keep their rows and gain the scope/tool columns."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.relational import SQLiteRelationalStore

_NOW = "2026-01-01T00:00:00+00:00"

_LEGACY_SCHEMA = (
    """
    CREATE TABLE profiles (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
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
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE pending_records (
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
    """,
)


def _columns(db_path: Path, table: str) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


@pytest.fixture
def legacy_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        for ddl in _LEGACY_SCHEMA:
            conn.execute(ddl)
        conn.execute("INSERT INTO profiles VALUES ('p1', 'default', 'language', 'zh', ?, ?)", (_NOW, _NOW))
        conn.execute(
            "INSERT INTO procedural_rules (id, user_id, content, trigger_text, action_text, priority, created_at, updated_at)"
            " VALUES ('r1', 'default', 'always cite', 'answer', 'cite sources', 7, ?, ?)",
            (_NOW, _NOW),
        )
        conn.execute(
            "INSERT INTO pending_records (id, user_id, memory_type, content, created_at)"
            " VALUES ('q1', 'default', 'semantic', 'candidate fact', ?)",
            (_NOW,),
        )
    return db_path


@pytest.mark.asyncio
async def test_legacy_database_is_upgraded_in_place(legacy_db: Path) -> None:
    store = SQLiteRelationalStore(str(legacy_db))
    try:
        assert await store.get_profile("language") == "zh"
    finally:
        await store.close()

    assert {"primary_namespace", "namespaces", "agent_id", "task_id"} <= _columns(legacy_db, "profiles")
    assert {
        "primary_namespace",
        "tool_name",
        "tool_rule_priority",
        "access_count",
        "last_accessed_at",
        "is_user_locked",
        "expected_valid_days",
    } <= _columns(legacy_db, "procedural_rules")
    assert {"resolution_action", "target_memory_id"} <= _columns(legacy_db, "pending_records")
    with sqlite3.connect(legacy_db) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert not {"profiles_legacy", "procedural_rules_legacy"} & tables


@pytest.mark.asyncio
async def test_upgrade_preserves_rows_and_applies_column_defaults(legacy_db: Path) -> None:
    store = SQLiteRelationalStore(str(legacy_db))
    try:
        rules = await store.list_rules()
        pending = await store.get_pending("q1")
        assert [(r.content, r.priority) for r in rules] == [("always cite", 7)]
        assert pending is not None
        assert pending.content == "candidate fact"
        assert pending.resolution_action.value == "store"
        assert pending.target_memory_id is None
    finally:
        await store.close()

    with sqlite3.connect(legacy_db) as conn:
        row = conn.execute(
            "SELECT primary_namespace, namespaces, tool_rule_priority, access_count, is_user_locked"
            " FROM procedural_rules WHERE id = 'r1'"
        ).fetchone()
    assert row == ("", "[]", "normal", 0, 0)


@pytest.mark.asyncio
async def test_upgrade_is_idempotent(legacy_db: Path) -> None:
    first = SQLiteRelationalStore(str(legacy_db))
    await first.get_profile("language")
    await first.close()

    second = SQLiteRelationalStore(str(legacy_db))
    try:
        assert await second.get_profile("language") == "zh"
        assert len(await second.list_rules()) == 1
    finally:
        await second.close()
