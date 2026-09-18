"""Bi-temporal schema migration, indexing, and supersession logic for SQLiteGraphStore.

[INPUT]
memory.graph.base::GraphRelationship (POS: 图存储抽象层)
memory.graph.exceptions::GraphQueryError (POS: 图存储异常类)

[OUTPUT]
migrate_temporal_schema: 确保双时态表结构与偏置唯一索引就绪
execute_create_relationship: 幂等创建或检索带时态区间的关系边
execute_supersede: 原子化闭合旧版本并置换创建新版本关系
execute_list_relationships: 支持时间切片旅行与归档状态过滤的关系查询

[POS]
SQLite 双时态图存储核心引擎。负责时间旅行快照过滤、偏置唯一索引维护及原子置换闭合。
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from uuid import uuid4

import aiosqlite

from myrm_agent_harness.toolkits.memory.graph.base import GraphRelationship
from myrm_agent_harness.toolkits.memory.graph.exceptions import GraphQueryError

logger = logging.getLogger(__name__)

RELATIONSHIP_COLUMNS = (
    "id, source_id, target_id, rel_type, properties, created_at, "
    "valid_from, valid_until, superseded_by, supersedes_id"
)


async def migrate_temporal_schema(conn: aiosqlite.Connection) -> None:
    """Ensure graph tables and bi-temporal columns/partial indexes exist."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS graph_nodes (
            id TEXT PRIMARY KEY,
            labels TEXT NOT NULL,
            properties TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS graph_relationships (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            rel_type TEXT NOT NULL,
            properties TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            valid_from TEXT,
            valid_until TEXT,
            superseded_by TEXT,
            supersedes_id TEXT,
            FOREIGN KEY (source_id) REFERENCES graph_nodes(id),
            FOREIGN KEY (target_id) REFERENCES graph_nodes(id)
        )
    """)

    async with conn.execute("PRAGMA table_info(graph_relationships)") as cursor:
        rows = await cursor.fetchall()
    existing_cols = {str(row[1]) for row in rows}

    alter_cols = [
        ("valid_from", "TEXT"),
        ("valid_until", "TEXT"),
        ("superseded_by", "TEXT"),
        ("supersedes_id", "TEXT"),
    ]
    for col_name, col_type in alter_cols:
        if col_name not in existing_cols:
            await conn.execute(f"ALTER TABLE graph_relationships ADD COLUMN {col_name} {col_type}")

    # If old idx_graph_rel_unique is unconditional, drop and recreate with WHERE valid_until IS NULL
    async with conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_graph_rel_unique'"
    ) as cursor:
        row = await cursor.fetchone()
        if row and row[0] and "WHERE" not in row[0].upper():
            await conn.execute("DROP INDEX IF EXISTS idx_graph_rel_unique")

    indexes = (
        "CREATE INDEX IF NOT EXISTS idx_graph_nodes_labels ON graph_nodes(labels)",
        "CREATE INDEX IF NOT EXISTS idx_graph_nodes_ns ON graph_nodes(json_extract(properties, '$.primary_namespace'))",
        "CREATE INDEX IF NOT EXISTS idx_graph_rel_source ON graph_relationships(source_id)",
        "CREATE INDEX IF NOT EXISTS idx_graph_rel_target ON graph_relationships(target_id)",
        "CREATE INDEX IF NOT EXISTS idx_graph_rel_type ON graph_relationships(rel_type)",
        "CREATE INDEX IF NOT EXISTS idx_graph_rel_source_type ON graph_relationships(source_id, rel_type)",
        # Uniqueness only enforced on active edges (where valid_until IS NULL)
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_rel_unique "
        "ON graph_relationships(source_id, target_id, rel_type) WHERE valid_until IS NULL",
        # Fast lookup for active outgoing edges
        "CREATE INDEX IF NOT EXISTS idx_graph_rel_active "
        "ON graph_relationships(source_id, rel_type) WHERE valid_until IS NULL",
        # Time-travel queries filtering on valid window
        "CREATE INDEX IF NOT EXISTS idx_graph_rel_valid_window "
        "ON graph_relationships(valid_from, valid_until)",
        # Fast lineage traversal
        "CREATE INDEX IF NOT EXISTS idx_graph_rel_superseded "
        "ON graph_relationships(superseded_by) WHERE superseded_by IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS idx_graph_rel_supersedes "
        "ON graph_relationships(supersedes_id) WHERE supersedes_id IS NOT NULL",
    )
    for sql in indexes:
        await conn.execute(sql)
    await conn.commit()


def build_temporal_where_clause(
    as_of_time: str | None = None,
    include_superseded: bool = False,
    table_prefix: str = "",
) -> tuple[str, list[str]]:
    """Build WHERE clause predicate and parameters for temporal validity filtering.

    - include_superseded=True: No temporal filter (returns full history).
    - as_of_time provided: Point-in-time snapshot (valid_from <= t < valid_until).
    - default: Current active edges only (valid_until IS NULL).
    """
    if include_superseded:
        return "", []

    prefix = f"{table_prefix}." if table_prefix else ""
    if as_of_time is not None:
        clause = (
            f"({prefix}valid_from IS NULL OR {prefix}valid_from <= ?) "
            f"AND ({prefix}valid_until IS NULL OR {prefix}valid_until > ?)"
        )
        return clause, [as_of_time, as_of_time]

    return f"{prefix}valid_until IS NULL", []


def row_to_relationship(row: tuple[object, ...]) -> GraphRelationship:
    """Deserialize a database row into a GraphRelationship instance."""
    raw_props = row[4]
    parsed_props: dict[str, str | int | float] = {}
    if isinstance(raw_props, str) and raw_props:
        try:
            parsed_props = json.loads(raw_props)
        except Exception:
            parsed_props = {}

    return GraphRelationship(
        id=str(row[0]),
        start_id=str(row[1]),
        end_id=str(row[2]),
        rel_type=str(row[3]),
        properties=parsed_props,
        created_at=str(row[5]) if row[5] is not None else None,
        valid_from=str(row[6]) if row[6] is not None else None,
        valid_until=str(row[7]) if row[7] is not None else None,
        superseded_by=str(row[8]) if row[8] is not None else None,
        supersedes_id=str(row[9]) if row[9] is not None else None,
    )


async def execute_create_relationship(
    conn: aiosqlite.Connection,
    start_id: str,
    end_id: str,
    rel_type: str,
    properties: dict[str, str | int | float] | None = None,
    *,
    created_at: str | None = None,
    valid_from: str | None = None,
    valid_until: str | None = None,
    superseded_by: str | None = None,
    supersedes_id: str | None = None,
) -> GraphRelationship:
    """Idempotently insert or retrieve an active relationship with temporal bounds."""
    try:
        check_sql = (
            f"SELECT {RELATIONSHIP_COLUMNS} FROM graph_relationships "
            "WHERE source_id = ? AND target_id = ? AND rel_type = ? AND valid_until IS NULL LIMIT 1"
        )
        async with conn.execute(check_sql, (start_id, end_id, rel_type)) as cursor:
            existing = await cursor.fetchone()

        if existing is not None:
            return row_to_relationship(existing)

        rel_id = str(uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        c_at = created_at or now_iso
        v_from = valid_from or now_iso
        props_json = json.dumps(properties or {})

        insert_sql = (
            "INSERT OR IGNORE INTO graph_relationships "
            "(id, source_id, target_id, rel_type, properties, created_at, "
            "valid_from, valid_until, superseded_by, supersedes_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        await conn.execute(
            insert_sql,
            (
                rel_id,
                start_id,
                end_id,
                rel_type,
                props_json,
                c_at,
                v_from,
                valid_until,
                superseded_by,
                supersedes_id,
            ),
        )
        await conn.commit()

        return GraphRelationship(
            id=rel_id,
            start_id=start_id,
            end_id=end_id,
            rel_type=rel_type,
            properties=properties or {},
            created_at=c_at,
            valid_from=v_from,
            valid_until=valid_until,
            superseded_by=superseded_by,
            supersedes_id=supersedes_id,
        )
    except Exception as e:
        raise GraphQueryError(f"Failed to create relationship: {e}") from e


async def execute_supersede(
    conn: aiosqlite.Connection,
    old_rel_id: str,
    new_end_id: str | None = None,
    new_rel_type: str | None = None,
    new_properties: dict[str, str | int | float] | None = None,
    *,
    as_of_time: str | None = None,
    valid_from: str | None = None,
    valid_until: str | None = None,
) -> tuple[GraphRelationship, GraphRelationship]:
    """Atomically close the old relationship and insert its superseding replacement."""
    try:
        fetch_sql = f"SELECT {RELATIONSHIP_COLUMNS} FROM graph_relationships WHERE id = ?"
        async with conn.execute(fetch_sql, (old_rel_id,)) as cursor:
            old_row = await cursor.fetchone()

        if old_row is None:
            raise GraphQueryError(f"Relationship not found for supersession: {old_rel_id}")

        old_rel = row_to_relationship(old_row)
        if old_rel.valid_until is not None:
            logger.warning("Relationship %s is already superseded/closed (valid_until=%s)", old_rel_id, old_rel.valid_until)

        new_rel_id = str(uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        switch_time = as_of_time or now_iso

        if old_rel.valid_from and switch_time < old_rel.valid_from:
            raise GraphQueryError(
                f"switch_time ({switch_time}) cannot precede original valid_from ({old_rel.valid_from})"
            )

        # Close old relationship
        update_sql = "UPDATE graph_relationships SET valid_until = ?, superseded_by = ? WHERE id = ?"
        await conn.execute(update_sql, (switch_time, new_rel_id, old_rel_id))

        # Formulate new relationship
        target_id = new_end_id if new_end_id is not None else old_rel.end_id
        rel_type = new_rel_type if new_rel_type is not None else old_rel.rel_type
        props = new_properties if new_properties is not None else old_rel.properties
        n_valid_from = valid_from or switch_time

        insert_sql = (
            "INSERT INTO graph_relationships "
            "(id, source_id, target_id, rel_type, properties, created_at, "
            "valid_from, valid_until, superseded_by, supersedes_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)"
        )
        await conn.execute(
            insert_sql,
            (
                new_rel_id,
                old_rel.start_id,
                target_id,
                rel_type,
                json.dumps(props),
                now_iso,
                n_valid_from,
                valid_until,
                old_rel_id,
            ),
        )
        await conn.commit()

        superseded_old = GraphRelationship(
            id=old_rel.id,
            start_id=old_rel.start_id,
            end_id=old_rel.end_id,
            rel_type=old_rel.rel_type,
            properties=old_rel.properties,
            created_at=old_rel.created_at,
            valid_from=old_rel.valid_from,
            valid_until=switch_time,
            superseded_by=new_rel_id,
            supersedes_id=old_rel.supersedes_id,
        )

        new_rel = GraphRelationship(
            id=new_rel_id,
            start_id=old_rel.start_id,
            end_id=target_id,
            rel_type=rel_type,
            properties=props,
            created_at=now_iso,
            valid_from=n_valid_from,
            valid_until=valid_until,
            superseded_by=None,
            supersedes_id=old_rel_id,
        )

        return superseded_old, new_rel
    except GraphQueryError:
        await conn.rollback()
        raise
    except Exception as e:
        await conn.rollback()
        raise GraphQueryError(f"Failed to supersede relationship: {e}") from e


async def execute_list_relationships(
    conn: aiosqlite.Connection,
    *,
    limit: int = 50,
    offset: int = 0,
    node_ids: list[str] | None = None,
    as_of_time: str | None = None,
    include_superseded: bool = False,
) -> list[GraphRelationship]:
    """Query relationships with bi-temporal snapshot and superseded filtering."""
    try:
        temporal_clause, temporal_params = build_temporal_where_clause(
            as_of_time=as_of_time, include_superseded=include_superseded
        )
        where_clauses: list[str] = []
        params: list[str | int] = []
        if node_ids is not None:
            if not node_ids:
                return []
            placeholders = ",".join("?" for _ in node_ids)
            where_clauses.append(f"source_id IN ({placeholders}) AND target_id IN ({placeholders})")
            params.extend([*node_ids, *node_ids])
        if temporal_clause:
            where_clauses.append(temporal_clause)
            params.extend(temporal_params)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        sql = f"SELECT {RELATIONSHIP_COLUMNS} FROM graph_relationships {where_sql} ORDER BY id LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        async with conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
        return [row_to_relationship(row) for row in rows]
    except Exception as e:
        raise GraphQueryError(f"Failed to list relationships: {e}") from e

