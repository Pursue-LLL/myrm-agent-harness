"""Lightweight SQLite-backed Knowledge Graph Store for relational long-term memory.

[INPUT]
- toolkits.memory.graph_rrf.types::EntityNode, GraphTraversalPath, GraphTraversalResult, RelationEdge (POS:
  Data models and contract types for Knowledge Graph and Vector RRF Fusion Memory Engine.)

[OUTPUT]
- SQLiteGraphMemoryStore: Manages knowledge graph entities, relations, and memory associations in SQLite.

[POS]
Lightweight SQLite-backed Knowledge Graph Store for relational long-term memory.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections import deque
from pathlib import Path

from myrm_agent_harness.toolkits.memory.graph_rrf.types import (
    EntityNode,
    GraphTraversalPath,
    GraphTraversalResult,
    RelationEdge,
)


class SQLiteGraphMemoryStore:
    """Manages knowledge graph entities, relations, and memory associations in SQLite."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_graph_nodes (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    properties_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_graph_nodes_name
                    ON memory_graph_nodes(name);

                CREATE TABLE IF NOT EXISTS memory_graph_edges (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    weight REAL NOT NULL,
                    properties_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_graph_edges_src
                    ON memory_graph_edges(source_id);
                CREATE INDEX IF NOT EXISTS idx_graph_edges_tgt
                    ON memory_graph_edges(target_id);

                CREATE TABLE IF NOT EXISTS memory_graph_associations (
                    memory_id TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (memory_id, entity_id)
                );
                CREATE INDEX IF NOT EXISTS idx_assoc_entity
                    ON memory_graph_associations(entity_id);
                CREATE INDEX IF NOT EXISTS idx_assoc_memory
                    ON memory_graph_associations(memory_id);

                CREATE TABLE IF NOT EXISTS memory_contents (
                    memory_id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )

    def close(self) -> None:
        """Close database connection."""
        self._conn.close()

    def add_node(self, node: EntityNode) -> None:
        """Insert or replace an entity node."""
        props = json.dumps(node.properties, ensure_ascii=False)
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO memory_graph_nodes (id, name, entity_type, properties_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (node.id, node.name, node.entity_type, props, node.created_at),
            )

    def get_node(self, node_id: str) -> EntityNode | None:
        """Fetch node by primary id."""
        cursor = self._conn.execute(
            "SELECT id, name, entity_type, properties_json, created_at FROM memory_graph_nodes WHERE id = ?",
            (node_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return EntityNode(
            id=str(row["id"]),
            name=str(row["name"]),
            entity_type=str(row["entity_type"]),
            properties=json.loads(row["properties_json"]),
            created_at=float(row["created_at"]),
        )

    def find_node_by_name(self, name: str) -> EntityNode | None:
        """Find node by case-insensitive name."""
        cursor = self._conn.execute(
            "SELECT id, name, entity_type, properties_json, created_at FROM memory_graph_nodes WHERE LOWER(name) = LOWER(?)",
            (name,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return EntityNode(
            id=str(row["id"]),
            name=str(row["name"]),
            entity_type=str(row["entity_type"]),
            properties=json.loads(row["properties_json"]),
            created_at=float(row["created_at"]),
        )

    def add_edge(self, edge: RelationEdge) -> None:
        """Insert or replace a directed relationship edge."""
        props = json.dumps(edge.properties, ensure_ascii=False)
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO memory_graph_edges (id, source_id, target_id, relation_type, weight, properties_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    edge.id,
                    edge.source_id,
                    edge.target_id,
                    edge.relation_type,
                    edge.weight,
                    props,
                    edge.created_at,
                ),
            )

    def associate_memory(
        self, memory_id: str, entity_id: str, content: str = ""
    ) -> None:
        """Link a memory unit with an entity node, optionally recording text content."""
        now = time.time()
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO memory_graph_associations (memory_id, entity_id, created_at)
                VALUES (?, ?, ?)
                """,
                (memory_id, entity_id, now),
            )
            if content:
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO memory_contents (memory_id, content, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (memory_id, content, now),
                )

    def get_memory_content(self, memory_id: str) -> str:
        """Retrieve stored content for a memory id if present."""
        cursor = self._conn.execute(
            "SELECT content FROM memory_contents WHERE memory_id = ?",
            (memory_id,),
        )
        row = cursor.fetchone()
        return str(row["content"]) if row else ""

    def get_associated_memories(self, entity_ids: list[str]) -> list[str]:
        """Fetch all unique memory IDs linked to specified entities."""
        if not entity_ids:
            return []
        placeholders = ",".join("?" for _ in entity_ids)
        cursor = self._conn.execute(
            f"SELECT DISTINCT memory_id FROM memory_graph_associations WHERE entity_id IN ({placeholders})",
            entity_ids,
        )
        return [str(row["memory_id"]) for row in cursor.fetchall()]

    def traverse(
        self,
        seed_entity_ids: list[str],
        max_hops: int = 2,
        allowed_relations: list[str] | None = None,
        max_nodes_visited: int = 500,
    ) -> GraphTraversalResult:
        """Perform breadth-first graph traversal from seed entities."""
        if not seed_entity_ids or max_hops < 0:
            return GraphTraversalResult(
                nodes=[], edges=[], paths=[], associated_memory_ids=[]
            )

        visited_node_ids: set[str] = set()
        reached_nodes: dict[str, EntityNode] = {}
        reached_edges: dict[str, RelationEdge] = {}
        traversal_paths: list[GraphTraversalPath] = []

        # Initialize BFS queue: (node_id, current_depth)
        queue: deque[tuple[str, int]] = deque()
        for seed_id in seed_entity_ids:
            node = self.get_node(seed_id)
            if node:
                reached_nodes[node.id] = node
                visited_node_ids.add(node.id)
                queue.append((node.id, 0))

        rel_filter_clause = ""
        filter_params: list[str] = []
        if allowed_relations:
            placeholders = ",".join("?" for _ in allowed_relations)
            rel_filter_clause = f"AND relation_type IN ({placeholders})"
            filter_params = list(allowed_relations)

        while queue and len(visited_node_ids) < max_nodes_visited:
            curr_id, depth = queue.popleft()
            if depth >= max_hops:
                continue

            query = f"""
                SELECT id, source_id, target_id, relation_type, weight, properties_json, created_at
                FROM memory_graph_edges
                WHERE (source_id = ? OR target_id = ?) {rel_filter_clause}
            """
            cursor = self._conn.execute(
                query, [curr_id, curr_id, *filter_params]
            )
            for row in cursor.fetchall():
                edge_id = str(row["id"])
                src_id = str(row["source_id"])
                tgt_id = str(row["target_id"])
                neighbor_id = tgt_id if src_id == curr_id else src_id

                edge = RelationEdge(
                    id=edge_id,
                    source_id=src_id,
                    target_id=tgt_id,
                    relation_type=str(row["relation_type"]),
                    weight=float(row["weight"]),
                    properties=json.loads(row["properties_json"]),
                    created_at=float(row["created_at"]),
                )
                reached_edges[edge_id] = edge

                traversal_paths.append(
                    GraphTraversalPath(
                        source_id=curr_id,
                        target_id=neighbor_id,
                        relation_type=edge.relation_type,
                        depth=depth + 1,
                    )
                )

                if (
                    neighbor_id not in visited_node_ids
                    and len(visited_node_ids) < max_nodes_visited
                ):
                    visited_node_ids.add(neighbor_id)
                    neighbor_node = self.get_node(neighbor_id)
                    if neighbor_node:
                        reached_nodes[neighbor_node.id] = neighbor_node
                    queue.append((neighbor_id, depth + 1))

        assoc_mems = self.get_associated_memories(list(reached_nodes.keys()))
        return GraphTraversalResult(
            nodes=list(reached_nodes.values()),
            edges=list(reached_edges.values()),
            paths=traversal_paths,
            associated_memory_ids=assoc_mems,
        )
