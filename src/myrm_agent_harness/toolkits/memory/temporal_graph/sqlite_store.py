"""[POS]: src/myrm_agent_harness/toolkits/memory/temporal_graph/sqlite_store.py
[INPUT]: SQLite connection, TemporalEntityNode, and TemporalFactEdge models.
[OUTPUT]: SqliteTemporalGraphStore providing thread-safe persistent CRUD and relational edge queries.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from threading import Lock

from .models import TemporalEntityNode, TemporalFactEdge


class SqliteTemporalGraphStore:
    """Thread-safe SQLite storage for temporal knowledge graph entities and edges."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path or "/tmp/myrm_temporal_knowledge_graph.db")
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA busy_timeout=5000;")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS temporal_nodes (
                    node_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    attributes_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS temporal_edges (
                    edge_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    valid_from TEXT NOT NULL,
                    valid_until TEXT,
                    is_superseded INTEGER NOT NULL,
                    superseded_by TEXT,
                    confidence_score REAL NOT NULL,
                    access_count INTEGER NOT NULL,
                    last_accessed_at TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_temporal_edges_src_pred
                ON temporal_edges(source_id, predicate, is_superseded);
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_temporal_edges_target
                ON temporal_edges(target_id);
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_temporal_nodes_name_type
                ON temporal_nodes(name, entity_type);
                """
            )
            self._conn.commit()

    def save_node(self, node: TemporalEntityNode) -> TemporalEntityNode:
        """Inserts or updates an entity node in the graph."""
        attrs_json = json.dumps(node.attributes, ensure_ascii=False)
        updated_iso = node.updated_at.isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO temporal_nodes
                (node_id, name, entity_type, attributes_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (
                    node.node_id,
                    node.name,
                    node.entity_type,
                    attrs_json,
                    node.created_at.isoformat(),
                    updated_iso,
                ),
            )
            self._conn.commit()
        return node

    def get_node(self, node_id: str) -> TemporalEntityNode | None:
        """Retrieves a node by primary ID."""
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT node_id, name, entity_type, attributes_json, created_at, updated_at
                FROM temporal_nodes WHERE node_id = ?;
                """,
                (node_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_node(row)

    def find_node(self, name: str, entity_type: str | None = None) -> TemporalEntityNode | None:
        """Finds a node matching name and optional entity type."""
        query = "SELECT node_id, name, entity_type, attributes_json, created_at, updated_at FROM temporal_nodes WHERE name = ?"
        params: list[str] = [name]
        if entity_type:
            query += " AND entity_type = ?"
            params.append(entity_type)
        query += " LIMIT 1;"

        with self._lock:
            cur = self._conn.execute(query, params)
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_node(row)

    def list_nodes(self, entity_type: str | None = None, limit: int = 100) -> list[TemporalEntityNode]:
        """Lists stored entity nodes."""
        query = "SELECT node_id, name, entity_type, attributes_json, created_at, updated_at FROM temporal_nodes"
        params: list[str | int] = []
        if entity_type:
            query += " WHERE entity_type = ?"
            params.append(entity_type)
        query += " ORDER BY updated_at DESC LIMIT ?;"
        params.append(limit)

        with self._lock:
            cur = self._conn.execute(query, params)
            return [self._row_to_node(r) for r in cur.fetchall()]

    def save_edge(self, edge: TemporalFactEdge) -> TemporalFactEdge:
        """Inserts or updates a fact relationship edge."""
        valid_until_iso = edge.valid_until.isoformat() if edge.valid_until else None
        last_accessed_iso = edge.last_accessed_at.isoformat() if edge.last_accessed_at else None

        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO temporal_edges
                (edge_id, source_id, target_id, predicate, valid_from, valid_until,
                 is_superseded, superseded_by, confidence_score, access_count,
                 last_accessed_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    edge.edge_id,
                    edge.source_id,
                    edge.target_id,
                    edge.predicate,
                    edge.valid_from.isoformat(),
                    valid_until_iso,
                    1 if edge.is_superseded else 0,
                    edge.superseded_by,
                    edge.confidence_score,
                    edge.access_count,
                    last_accessed_iso,
                    edge.created_at.isoformat(),
                ),
            )
            self._conn.commit()
        return edge

    def get_edge(self, edge_id: str) -> TemporalFactEdge | None:
        """Retrieves a fact edge by ID."""
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT edge_id, source_id, target_id, predicate, valid_from, valid_until,
                       is_superseded, superseded_by, confidence_score, access_count,
                       last_accessed_at, created_at
                FROM temporal_edges WHERE edge_id = ?;
                """,
                (edge_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_edge(row)

    def get_edges_by_source_predicate(
        self,
        source_id: str,
        predicate: str,
        active_only: bool = True,
    ) -> list[TemporalFactEdge]:
        """Finds edges originating from source with specific predicate."""
        query = "SELECT edge_id, source_id, target_id, predicate, valid_from, valid_until, is_superseded, superseded_by, confidence_score, access_count, last_accessed_at, created_at FROM temporal_edges WHERE source_id = ? AND predicate = ?"
        params: list[str | int] = [source_id, predicate]
        if active_only:
            query += " AND is_superseded = 0"
        query += " ORDER BY valid_from DESC;"

        with self._lock:
            cur = self._conn.execute(query, params)
            return [self._row_to_edge(r) for r in cur.fetchall()]

    def get_out_edges(self, source_id: str, active_only: bool = True) -> list[TemporalFactEdge]:
        """Finds all outgoing edges from source entity."""
        query = "SELECT edge_id, source_id, target_id, predicate, valid_from, valid_until, is_superseded, superseded_by, confidence_score, access_count, last_accessed_at, created_at FROM temporal_edges WHERE source_id = ?"
        params: list[str | int] = [source_id]
        if active_only:
            query += " AND is_superseded = 0"
        query += " ORDER BY valid_from DESC;"

        with self._lock:
            cur = self._conn.execute(query, params)
            return [self._row_to_edge(r) for r in cur.fetchall()]

    def list_edges(
        self,
        predicate: str | None = None,
        active_only: bool = True,
        limit: int = 100,
    ) -> list[TemporalFactEdge]:
        """Lists edges with optional predicate and active-only filtering."""
        query = "SELECT edge_id, source_id, target_id, predicate, valid_from, valid_until, is_superseded, superseded_by, confidence_score, access_count, last_accessed_at, created_at FROM temporal_edges"
        conditions: list[str] = []
        params: list[str | int] = []

        if predicate:
            conditions.append("predicate = ?")
            params.append(predicate)
        if active_only:
            conditions.append("is_superseded = 0")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY valid_from DESC LIMIT ?;"
        params.append(limit)

        with self._lock:
            cur = self._conn.execute(query, params)
            return [self._row_to_edge(r) for r in cur.fetchall()]

    def delete_edge(self, edge_id: str) -> bool:
        """Deletes a fact edge."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM temporal_edges WHERE edge_id = ?;", (edge_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def delete_node(self, node_id: str) -> bool:
        """Deletes a node and associated edges."""
        with self._lock:
            self._conn.execute("DELETE FROM temporal_edges WHERE source_id = ? OR target_id = ?;", (node_id, node_id))
            cur = self._conn.execute("DELETE FROM temporal_nodes WHERE node_id = ?;", (node_id,))
            self._conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def _row_to_node(row: tuple[str, str, str, str, str, str]) -> TemporalEntityNode:
        attrs = json.loads(row[3]) if row[3] else {}
        return TemporalEntityNode(
            node_id=row[0],
            name=row[1],
            entity_type=row[2],
            attributes=attrs,
            created_at=datetime.fromisoformat(row[4]),
            updated_at=datetime.fromisoformat(row[5]),
        )

    @staticmethod
    def _row_to_edge(
        row: tuple[str, str, str, str, str, str | None, int, str | None, float, int, str | None, str],
    ) -> TemporalFactEdge:
        valid_until = datetime.fromisoformat(row[5]) if row[5] else None
        last_accessed = datetime.fromisoformat(row[10]) if row[10] else None
        return TemporalFactEdge(
            edge_id=row[0],
            source_id=row[1],
            target_id=row[2],
            predicate=row[3],
            valid_from=datetime.fromisoformat(row[4]),
            valid_until=valid_until,
            is_superseded=bool(row[6]),
            superseded_by=row[7],
            confidence_score=row[8],
            access_count=row[9],
            last_accessed_at=last_accessed,
            created_at=datetime.fromisoformat(row[11]),
        )
