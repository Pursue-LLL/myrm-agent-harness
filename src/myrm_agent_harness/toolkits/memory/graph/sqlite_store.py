"""SQLite Graph Store — zero-dependency graph backend using recursive CTE.

[INPUT]
memory.graph.base::GraphStore (POS: 图存储抽象层)
memory.graph.sqlite_temporal (POS: 双时态图存储核心引擎)
memory.graph.sqlite_traversal (POS: 递归 CTE 图遍历执行器)

[OUTPUT]
SQLiteGraphStore: 轻量异步 SQLite 图存储门面，支持双时态版本置换与递归 CTE 遍历

[POS]
轻量图存储门面。集成 aiosqlite、双时态快照查询与 CTE 因果遍历，提供零外部依赖图存储能力。
"""

import asyncio
import json
import logging
from pathlib import Path
from uuid import uuid4

import aiosqlite

from myrm_agent_harness.toolkits.memory.graph.base import (
    GraphNode,
    GraphQueryResult,
    GraphRelationship,
    GraphStats,
    GraphStore,
)
from myrm_agent_harness.toolkits.memory.graph.exceptions import (
    GraphConnectionError,
    GraphNotSupportedError,
    GraphQueryError,
)
from myrm_agent_harness.toolkits.memory.graph.sqlite_temporal import (
    execute_create_relationship,
    execute_list_relationships,
    execute_supersede,
    migrate_temporal_schema,
)
from myrm_agent_harness.toolkits.memory.graph.sqlite_traversal import (
    execute_causal_chain,
    execute_delete_all_by_owner,
    execute_delete_subgraph,
    execute_related_nodes,
    execute_related_nodes_with_depth,
)

logger = logging.getLogger(__name__)


class SQLiteGraphStore(GraphStore):
    """SQLite graph store with recursive CTE, temporal support, and WAL mode.

    Features:
    - Async I/O via aiosqlite
    - WAL mode (50-100% concurrency improvement)
    - 64MB query cache + 256MB mmap
    - Connection reuse with double-checked locking
    - Bi-temporal valid-time tracking and relationship superseding
    - Cycle detection in causal chain queries
    - Composite index optimization
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path).expanduser().resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection: aiosqlite.Connection | None = None
        self._connection_lock = asyncio.Lock()
        self._initialized = False
        logger.info("SQLiteGraphStore initialized: %s", self._db_path)

    async def _get_connection(self) -> aiosqlite.Connection:
        if self._connection is None:
            async with self._connection_lock:
                if self._connection is None:
                    try:
                        from myrm_agent_harness.utils.db.sqlite import prepare_database_file

                        prepare_database_file(self._db_path)
                        self._connection = await aiosqlite.connect(str(self._db_path))
                        await self._init_connection_settings()
                        await self._init_tables()
                    except Exception as e:
                        raise GraphConnectionError(f"Failed to connect to SQLite: {e}") from e
        return self._connection

    async def _init_connection_settings(self) -> None:
        if self._connection is None:
            return
        from dataclasses import replace

        from myrm_agent_harness.utils.db.sqlite import DURABLE, harden_connection_async

        await harden_connection_async(
            self._connection,
            replace(DURABLE, page_size_bytes=4096),
            db_path=self._db_path,
        )
        await self._connection.commit()

    async def _init_tables(self) -> None:
        if self._initialized or self._connection is None:
            return
        try:
            await migrate_temporal_schema(self._connection)
            self._initialized = True
        except Exception as e:
            raise GraphConnectionError(f"Failed to initialize tables: {e}") from e

    # ── Core CRUD ────────────────────────────────────────────────────

    async def create_node(self, labels: list[str], properties: dict[str, str | int | float | bool]) -> GraphNode:
        conn = await self._get_connection()
        try:
            node_id = str(properties.get("id", str(uuid4())))
            await conn.execute(
                "INSERT OR REPLACE INTO graph_nodes (id, labels, properties) VALUES (?, ?, ?)",
                (node_id, json.dumps(labels), json.dumps(properties)),
            )
            await conn.commit()
            return GraphNode(id=node_id, labels=labels, properties=properties)
        except Exception as e:
            raise GraphQueryError(f"Failed to create node: {e}") from e

    async def get_or_create_node(
        self, labels: list[str], match_keys: list[str], properties: dict[str, str | int | float | bool]
    ) -> GraphNode:
        conn = await self._get_connection()
        try:
            where_parts = ["labels = ?"]
            params: list[str | int | float | bool] = [json.dumps(labels)]
            for key in match_keys:
                where_parts.append(f"json_extract(properties, '$.{key}') = ?")
                params.append(properties[key])

            sql = f"SELECT id, labels, properties FROM graph_nodes WHERE {' AND '.join(where_parts)} LIMIT 1"
            async with conn.execute(sql, params) as cursor:
                row = await cursor.fetchone()

            if row is not None:
                return GraphNode(id=row[0], labels=json.loads(row[1]), properties=json.loads(row[2]))
            return await self.create_node(labels, properties)
        except Exception as e:
            raise GraphQueryError(f"Failed to get_or_create node: {e}") from e

    async def create_relationship(
        self,
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
        """Idempotent: returns existing active relationship if (start, end, type) already exists."""
        conn = await self._get_connection()
        return await execute_create_relationship(
            conn,
            start_id,
            end_id,
            rel_type,
            properties,
            created_at=created_at,
            valid_from=valid_from,
            valid_until=valid_until,
            superseded_by=superseded_by,
            supersedes_id=supersedes_id,
        )

    async def supersede_relationship(
        self,
        old_rel_id: str,
        new_end_id: str | None = None,
        new_rel_type: str | None = None,
        new_properties: dict[str, str | int | float] | None = None,
        *,
        as_of_time: str | None = None,
        valid_from: str | None = None,
        valid_until: str | None = None,
    ) -> tuple[GraphRelationship, GraphRelationship]:
        """Atomically close the old relationship and create its replacement."""
        conn = await self._get_connection()
        return await execute_supersede(
            conn,
            old_rel_id=old_rel_id,
            new_end_id=new_end_id,
            new_rel_type=new_rel_type,
            new_properties=new_properties,
            as_of_time=as_of_time,
            valid_from=valid_from,
            valid_until=valid_until,
        )

    async def get_node(self, node_id: str) -> GraphNode | None:
        conn = await self._get_connection()
        try:
            async with conn.execute(
                "SELECT id, labels, properties FROM graph_nodes WHERE id = ?", (node_id,)
            ) as cursor:
                row = await cursor.fetchone()
            if row:
                return GraphNode(id=row[0], labels=json.loads(row[1]), properties=json.loads(row[2]))
            return None
        except Exception as e:
            logger.warning("Failed to get node %s: %s", node_id, e)
            return None

    async def find_nodes(
        self, labels: list[str], filters: dict[str, str | int | float | bool], *, limit: int = 100
    ) -> list[GraphNode]:
        conn = await self._get_connection()
        try:
            where_parts = ["labels = ?"]
            params: list[str | int | float | bool] = [json.dumps(labels)]
            for key, value in filters.items():
                where_parts.append(f"json_extract(properties, '$.{key}') = ?")
                params.append(value)
            params.append(limit)

            sql = (
                f"SELECT id, labels, properties FROM graph_nodes WHERE {' AND '.join(where_parts)} "
                "ORDER BY created_at DESC LIMIT ?"
            )
            async with conn.execute(sql, params) as cursor:
                rows = await cursor.fetchall()

            return [GraphNode(id=row[0], labels=json.loads(row[1]), properties=json.loads(row[2])) for row in rows]
        except Exception as e:
            raise GraphQueryError(f"Failed to find nodes: {e}") from e

    async def update_node_properties(
        self, node_id: str, properties: dict[str, str | int | float | bool]
    ) -> GraphNode | None:
        conn = await self._get_connection()
        existing = await self.get_node(node_id)
        if existing is None:
            return None
        merged_properties = dict(existing.properties)
        merged_properties.update(properties)
        try:
            await conn.execute(
                "UPDATE graph_nodes SET properties = ? WHERE id = ?", (json.dumps(merged_properties), node_id)
            )
            await conn.commit()
            return GraphNode(id=existing.id, labels=existing.labels, properties=merged_properties)
        except Exception as e:
            raise GraphQueryError(f"Failed to update node properties: {e}") from e

    async def delete_node(self, node_id: str) -> bool:
        conn = await self._get_connection()
        try:
            await conn.execute(
                "DELETE FROM graph_relationships WHERE source_id = ? OR target_id = ?", (node_id, node_id)
            )
            cursor = await conn.execute("DELETE FROM graph_nodes WHERE id = ?", (node_id,))
            await conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.warning("Failed to delete node %s: %s", node_id, e)
            return False

    # ── Graph traversal ──────────────────────────────────────────────

    async def get_causal_chain(
        self, start_id: str, depth: int = 5, relation_types: list[str] | None = None
    ) -> list[str]:
        conn = await self._get_connection()
        return await execute_causal_chain(conn, start_id, depth, relation_types)

    async def get_related_nodes(self, node_id: str, rel_type: str = "MENTIONS") -> list[str]:
        conn = await self._get_connection()
        return await execute_related_nodes(conn, node_id, rel_type)

    async def get_related_nodes_with_depth(
        self, node_id: str, rel_type: str = "MENTIONS", max_depth: int = 2
    ) -> list[tuple[str, int]]:
        conn = await self._get_connection()
        return await execute_related_nodes_with_depth(conn, node_id, rel_type, max_depth)

    # ── Subgraph operations ──────────────────────────────────────────

    async def delete_subgraph(self, node_id: str) -> int:
        """Delete a node and all its relationships."""
        conn = await self._get_connection()
        return await execute_delete_subgraph(conn, node_id)

    async def delete_all_by_owner(self, owner_id: str, *, owner_key: str = "user_id") -> int:
        """Delete all nodes and relationships whose node properties contain the owner_id."""
        conn = await self._get_connection()
        return await execute_delete_all_by_owner(conn, owner_id, owner_key=owner_key)

    # ── Unsupported operations ───────────────────────────────────────

    async def execute_cypher(
        self, query: str, params: dict[str, str | int | float | bool | list[str]] | None = None
    ) -> GraphQueryResult:
        raise GraphNotSupportedError("SQLite does not support Cypher. Use get_causal_chain() instead.")

    # ── Listing & Stats (for visualization API) ─────────────────────

    async def list_nodes(
        self, *, limit: int = 50, offset: int = 0, namespace: str | None = None
    ) -> list[GraphNode]:
        conn = await self._get_connection()
        if namespace:
            query = (
                "SELECT id, labels, properties FROM graph_nodes "
                "WHERE json_extract(properties, '$.primary_namespace') = ? "
                "ORDER BY id LIMIT ? OFFSET ?"
            )
            params: tuple[str | int, ...] = (namespace, limit, offset)
        else:
            query = "SELECT id, labels, properties FROM graph_nodes ORDER BY id LIMIT ? OFFSET ?"
            params = (limit, offset)

        async with conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [
            GraphNode(
                id=row[0],
                labels=json.loads(row[1]) if row[1] else [],
                properties=json.loads(row[2]) if row[2] else {},
            )
            for row in rows
        ]

    async def list_relationships(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        node_ids: list[str] | None = None,
        as_of_time: str | None = None,
        include_superseded: bool = False,
    ) -> list[GraphRelationship]:
        conn = await self._get_connection()
        return await execute_list_relationships(
            conn,
            limit=limit,
            offset=offset,
            node_ids=node_ids,
            as_of_time=as_of_time,
            include_superseded=include_superseded,
        )

    async def get_stats(self) -> GraphStats:
        conn = await self._get_connection()
        async with conn.execute("SELECT COUNT(*) FROM graph_nodes") as c:
            node_count = (await c.fetchone())[0]
        async with conn.execute("SELECT COUNT(*) FROM graph_relationships") as c:
            rel_count = (await c.fetchone())[0]

        label_counts: dict[str, int] = {}
        async with conn.execute("SELECT labels FROM graph_nodes") as c:
            for row in await c.fetchall():
                for label in json.loads(row[0]) if row[0] else []:
                    label_counts[label] = label_counts.get(label, 0) + 1

        rel_type_counts: dict[str, int] = {}
        async with conn.execute("SELECT rel_type, COUNT(*) FROM graph_relationships GROUP BY rel_type") as c:
            for row in await c.fetchall():
                rel_type_counts[row[0]] = row[1]

        return GraphStats(
            node_count=node_count,
            relationship_count=rel_count,
            node_label_counts=label_counts,
            relationship_type_counts=rel_type_counts,
        )

    # ── Lifecycle ────────────────────────────────────────────────────

    async def health_check(self) -> bool:
        try:
            conn = await self._get_connection()
            async with conn.execute("SELECT 1") as cursor:
                await cursor.fetchone()
            return True
        except Exception as e:
            logger.error("SQLite health check failed: %s", e)
            return False

    async def close(self) -> None:
        if self._connection is not None:
            from myrm_agent_harness.utils.db.sqlite import checkpoint_truncate_async

            await checkpoint_truncate_async(self._connection)
            await self._connection.close()
            self._connection = None
            logger.info("SQLiteGraphStore closed")
