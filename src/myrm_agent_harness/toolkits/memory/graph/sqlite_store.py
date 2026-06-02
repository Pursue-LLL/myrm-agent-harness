"""SQLite Graph Store — zero-dependency graph backend using recursive CTE.


[INPUT]
myrm_agent_harness.toolkits.memory.graph.base (POS: Graph store abstraction layer)
myrm_agent_harness.toolkits.memory.graph.exceptions

[OUTPUT]
SQLiteGraphStore: Async SQLite graph store with WAL mode, connection reuse,
                  recursive CTE causal-chain queries, and cycle detection.

[POS]
Lightweight graph store backed by aiosqlite. Uses recursive CTE for graph queries,
WAL mode + 64MB cache + connection reuse for high-performance async I/O.
UNIQUE(source_id, target_id, rel_type) index prevents relationship accumulation.
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

logger = logging.getLogger(__name__)


class SQLiteGraphStore(GraphStore):
    """SQLite graph store with recursive CTE and WAL mode.

    Features:
    - Async I/O via aiosqlite
    - WAL mode (50-100% concurrency improvement)
    - 64MB query cache + 256MB mmap
    - Connection reuse with double-checked locking
    - Cycle detection in causal chain queries
    - Composite index optimization

    Example::

        async with SQLiteGraphStore("~/.app/graph.db") as store:
            node = await store.create_node(
                labels=["Memory"],
                properties={"id": "mem_123", "content": "..."}
            )
            chain = await store.get_causal_chain("mem_123", depth=5)
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
            await self._connection.execute("""
                CREATE TABLE IF NOT EXISTS graph_nodes (
                    id TEXT PRIMARY KEY,
                    labels TEXT NOT NULL,
                    properties TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await self._connection.execute("""
                CREATE TABLE IF NOT EXISTS graph_relationships (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    rel_type TEXT NOT NULL,
                    properties TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (source_id) REFERENCES graph_nodes(id),
                    FOREIGN KEY (target_id) REFERENCES graph_nodes(id)
                )
            """)
            for idx_sql in (
                "CREATE INDEX IF NOT EXISTS idx_graph_rel_source ON graph_relationships(source_id)",
                "CREATE INDEX IF NOT EXISTS idx_graph_rel_target ON graph_relationships(target_id)",
                "CREATE INDEX IF NOT EXISTS idx_graph_rel_type ON graph_relationships(rel_type)",
                "CREATE INDEX IF NOT EXISTS idx_graph_rel_source_type ON graph_relationships(source_id, rel_type)",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_rel_unique ON graph_relationships(source_id, target_id, rel_type)",
            ):
                await self._connection.execute(idx_sql)
            await self._connection.commit()
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
        self, start_id: str, end_id: str, rel_type: str, properties: dict[str, str | int | float] | None = None
    ) -> GraphRelationship:
        """Idempotent: returns existing relationship if (start, end, type) already exists."""
        conn = await self._get_connection()
        try:
            async with conn.execute(
                "SELECT id, properties FROM graph_relationships WHERE source_id = ? AND target_id = ? AND rel_type = ? LIMIT 1",
                (start_id, end_id, rel_type),
            ) as cursor:
                existing = await cursor.fetchone()

            if existing is not None:
                return GraphRelationship(
                    id=existing[0],
                    start_id=start_id,
                    end_id=end_id,
                    rel_type=rel_type,
                    properties=json.loads(existing[1]) if existing[1] else {},
                )

            rel_id = str(uuid4())
            await conn.execute(
                "INSERT OR IGNORE INTO graph_relationships (id, source_id, target_id, rel_type, properties) VALUES (?, ?, ?, ?, ?)",
                (rel_id, start_id, end_id, rel_type, json.dumps(properties or {})),
            )
            await conn.commit()
            return GraphRelationship(
                id=rel_id, start_id=start_id, end_id=end_id, rel_type=rel_type, properties=properties or {}
            )
        except Exception as e:
            raise GraphQueryError(f"Failed to create relationship: {e}") from e

    async def get_node(self, node_id: str) -> GraphNode | None:
        conn = await self._get_connection()
        try:
            async with conn.execute("SELECT id, labels, properties FROM graph_nodes WHERE id = ?", (node_id,)) as cursor:
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
                "ORDER BY created_at ASC LIMIT ?"
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
        if relation_types is None:
            relation_types = ["causes"]
        try:
            base_cond = " OR ".join(["rel_type = ?" for _ in relation_types])
            recursive_cond = " OR ".join(["r.rel_type = ?" for _ in relation_types])
            query = f"""
                WITH RECURSIVE causal_chain AS (
                    SELECT source_id, target_id, rel_type, 1 as depth,
                           source_id || ',' || target_id as path
                    FROM graph_relationships
                    WHERE source_id = ? AND ({base_cond})

                    UNION ALL

                    SELECT r.source_id, r.target_id, r.rel_type, c.depth + 1,
                           c.path || ',' || r.target_id
                    FROM graph_relationships r
                    INNER JOIN causal_chain c ON r.source_id = c.target_id
                    WHERE c.depth < ? AND ({recursive_cond})
                      AND instr(c.path, r.target_id) = 0
                )
                SELECT DISTINCT target_id, depth FROM causal_chain ORDER BY depth
            """
            params = [start_id, *relation_types, depth, *relation_types]
            async with conn.execute(query, params) as cursor:
                results = await cursor.fetchall()
            return [row[0] for row in results]
        except Exception as e:
            raise GraphQueryError(f"Causal chain query failed: {e}") from e

    async def get_related_nodes(self, node_id: str, rel_type: str = "MENTIONS") -> list[str]:
        conn = await self._get_connection()
        try:
            query = """
                SELECT DISTINCT r2.source_id
                FROM graph_relationships r1
                JOIN graph_relationships r2 ON r1.target_id = r2.target_id
                WHERE r1.source_id = ? AND r1.rel_type = ?
                  AND r2.rel_type = ? AND r2.source_id != ?
            """
            async with conn.execute(query, (node_id, rel_type, rel_type, node_id)) as cursor:
                rows = await cursor.fetchall()
            return [row[0] for row in rows]
        except Exception as e:
            logger.warning("get_related_nodes failed: %s", e)
            return []

    async def get_related_nodes_with_depth(
        self, node_id: str, rel_type: str = "MENTIONS", max_depth: int = 2
    ) -> list[tuple[str, int]]:
        conn = await self._get_connection()
        try:
            # Path-based cycle detection (SQLite forbids subquery self-reference in recursive CTE)
            query = """
                WITH RECURSIVE related AS (
                    SELECT DISTINCT r2.source_id AS node_id, 1 AS depth,
                           ',' || r2.source_id || ',' AS path
                    FROM graph_relationships r1
                    JOIN graph_relationships r2 ON r1.target_id = r2.target_id
                    WHERE r1.source_id = ? AND r1.rel_type = ?
                      AND r2.rel_type = ? AND r2.source_id != ?

                    UNION ALL

                    SELECT DISTINCT r2.source_id AS node_id, rd.depth + 1 AS depth,
                           rd.path || r2.source_id || ',' AS path
                    FROM related rd
                    JOIN graph_relationships r1 ON r1.source_id = rd.node_id
                    JOIN graph_relationships r2 ON r1.target_id = r2.target_id
                    WHERE r1.rel_type = ?
                      AND r2.rel_type = ? AND r2.source_id != ?
                      AND instr(rd.path, ',' || r2.source_id || ',') = 0
                      AND rd.depth < ?
                )
                SELECT node_id, MIN(depth) AS depth FROM related
                GROUP BY node_id ORDER BY depth
            """
            params = [node_id, rel_type, rel_type, node_id, rel_type, rel_type, node_id, max_depth]
            async with conn.execute(query, params) as cursor:
                rows = await cursor.fetchall()
            return [(row[0], row[1]) for row in rows]
        except Exception as e:
            logger.warning("get_related_nodes_with_depth failed: %s", e)
            return []

    # ── Subgraph operations ──────────────────────────────────────────

    async def delete_subgraph(self, node_id: str) -> int:
        """Delete a node and all its relationships."""
        conn = await self._get_connection()
        try:
            cursor_rels = await conn.execute(
                "DELETE FROM graph_relationships WHERE source_id = ? OR target_id = ?", (node_id, node_id)
            )
            cursor_node = await conn.execute("DELETE FROM graph_nodes WHERE id = ?", (node_id,))
            await conn.commit()
            return cursor_rels.rowcount + cursor_node.rowcount
        except Exception as e:
            logger.warning("delete_subgraph failed for %s: %s", node_id, e)
            return 0

    async def delete_all_by_owner(self, owner_id: str, *, owner_key: str = "user_id") -> int:
        """Delete all nodes and relationships whose node properties contain the owner_id."""
        conn = await self._get_connection()
        try:
            async with conn.execute(
                f"SELECT id FROM graph_nodes WHERE json_extract(properties, '$.{owner_key}') = ?", (owner_id,)
            ) as cursor:
                node_ids = [row[0] for row in await cursor.fetchall()]

            if not node_ids:
                return 0

            placeholders = ",".join("?" for _ in node_ids)
            cursor_rels = await conn.execute(
                f"DELETE FROM graph_relationships WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
                [*node_ids, *node_ids],
            )
            cursor_nodes = await conn.execute(f"DELETE FROM graph_nodes WHERE id IN ({placeholders})", node_ids)
            await conn.commit()
            return cursor_rels.rowcount + cursor_nodes.rowcount
        except Exception as e:
            logger.warning("delete_all_by_owner failed for %s: %s", owner_id, e)
            return 0

    # ── Unsupported operations ───────────────────────────────────────

    async def execute_cypher(
        self, query: str, params: dict[str, str | int | float | bool | list[str]] | None = None
    ) -> GraphQueryResult:
        raise GraphNotSupportedError("SQLite does not support Cypher. Use get_causal_chain() instead.")

    # ── Listing & Stats (for visualization API) ─────────────────────

    async def list_nodes(self, *, limit: int = 50, offset: int = 0) -> list[GraphNode]:
        conn = await self._get_connection()
        async with conn.execute(
            "SELECT id, labels, properties FROM graph_nodes ORDER BY id LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            GraphNode(
                id=row[0],
                labels=json.loads(row[1]) if row[1] else [],
                properties=json.loads(row[2]) if row[2] else {},
            )
            for row in rows
        ]

    async def list_relationships(self, *, limit: int = 50, offset: int = 0) -> list[GraphRelationship]:
        conn = await self._get_connection()
        async with conn.execute(
            "SELECT id, source_id, target_id, rel_type, properties FROM graph_relationships ORDER BY id LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            GraphRelationship(
                id=row[0],
                start_id=row[1],
                end_id=row[2],
                rel_type=row[3],
                properties=json.loads(row[4]) if row[4] else {},
            )
            for row in rows
        ]

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
        async with conn.execute(
            "SELECT rel_type, COUNT(*) FROM graph_relationships GROUP BY rel_type"
        ) as c:
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
