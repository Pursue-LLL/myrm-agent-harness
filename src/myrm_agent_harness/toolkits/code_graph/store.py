"""SQLite-backed code knowledge graph storage.

Manages nodes (functions, classes, modules) and edges (calls, imports, inherits)
with FTS5 full-text indexing for structural code search.

[INPUT]
- pathlib.Path (POS: database file path)

[OUTPUT]
- CodeGraphStore: async-free SQLite graph store with FTS5, schema migrations,
  and bounded query operations.

[POS]
Persistent code structure storage for AST-parsed code relationships. Provides
graph queries (impact radius, callers, dependencies) and full-text search over
qualified symbol names.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Sequence

logger = logging.getLogger(__name__)


class NodeKind(str, Enum):
    FILE = "File"
    CLASS = "Class"
    FUNCTION = "Function"
    METHOD = "Method"
    MODULE = "Module"
    TYPE = "Type"
    INTERFACE = "Interface"
    TRAIT = "Trait"
    STRUCT = "Struct"


class EdgeKind(str, Enum):
    CALLS = "CALLS"
    IMPORTS_FROM = "IMPORTS_FROM"
    INHERITS = "INHERITS"
    IMPLEMENTS = "IMPLEMENTS"
    CONTAINS = "CONTAINS"
    TESTED_BY = "TESTED_BY"
    DEPENDS_ON = "DEPENDS_ON"
    REFERENCES = "REFERENCES"


class ConfidenceTier(str, Enum):
    EXTRACTED = "EXTRACTED"
    INFERRED = "INFERRED"
    RESOLVED = "RESOLVED"


@dataclass(frozen=True, slots=True)
class GraphNode:
    kind: NodeKind
    name: str
    qualified_name: str
    file_path: str
    line_start: int
    line_end: int
    language: str
    parent_name: str = ""
    params: str = ""
    return_type: str = ""
    modifiers: str = ""
    is_test: bool = False


@dataclass(frozen=True, slots=True)
class GraphEdge:
    kind: EdgeKind
    source_qualified: str
    target_qualified: str
    file_path: str
    line: int = 0
    confidence: float = 1.0
    confidence_tier: ConfidenceTier = ConfidenceTier.EXTRACTED


@dataclass(slots=True)
class ImpactResult:
    target: str
    affected_nodes: list[dict[str, str | int]] = field(default_factory=list)
    affected_files: list[str] = field(default_factory=list)
    depth_reached: int = 0
    total_files_scanned: int = 0


_SCHEMA_VERSION = 2

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS _schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    qualified_name TEXT NOT NULL UNIQUE,
    file_path TEXT NOT NULL,
    line_start INTEGER NOT NULL DEFAULT 0,
    line_end INTEGER NOT NULL DEFAULT 0,
    language TEXT NOT NULL DEFAULT '',
    parent_name TEXT NOT NULL DEFAULT '',
    params TEXT NOT NULL DEFAULT '',
    return_type TEXT NOT NULL DEFAULT '',
    modifiers TEXT NOT NULL DEFAULT '',
    is_test INTEGER NOT NULL DEFAULT 0,
    file_hash TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(file_path);
CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);
CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);

CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    source_qualified TEXT NOT NULL,
    target_qualified TEXT NOT NULL,
    file_path TEXT NOT NULL,
    line INTEGER NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 1.0,
    confidence_tier TEXT NOT NULL DEFAULT 'EXTRACTED',
    updated_at REAL NOT NULL,
    UNIQUE(kind, source_qualified, target_qualified)
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_qualified);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_qualified);
CREATE INDEX IF NOT EXISTS idx_edges_kind ON edges(kind);
CREATE INDEX IF NOT EXISTS idx_edges_target_kind ON edges(target_qualified, kind);
CREATE INDEX IF NOT EXISTS idx_edges_source_kind ON edges(source_qualified, kind);
CREATE INDEX IF NOT EXISTS idx_edges_file ON edges(file_path);

CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
    name,
    qualified_name,
    file_path,
    content=nodes,
    content_rowid=id,
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS nodes_ai AFTER INSERT ON nodes BEGIN
    INSERT INTO nodes_fts(rowid, name, qualified_name, file_path)
    VALUES (new.id, new.name, new.qualified_name, new.file_path);
END;

CREATE TRIGGER IF NOT EXISTS nodes_ad AFTER DELETE ON nodes BEGIN
    INSERT INTO nodes_fts(nodes_fts, rowid, name, qualified_name, file_path)
    VALUES ('delete', old.id, old.name, old.qualified_name, old.file_path);
END;

CREATE TRIGGER IF NOT EXISTS nodes_au AFTER UPDATE ON nodes BEGIN
    INSERT INTO nodes_fts(nodes_fts, rowid, name, qualified_name, file_path)
    VALUES ('delete', old.id, old.name, old.qualified_name, old.file_path);
    INSERT INTO nodes_fts(rowid, name, qualified_name, file_path)
    VALUES (new.id, new.name, new.qualified_name, new.file_path);
END;
"""

MAX_IMPACT_DEPTH = 5
MAX_IMPACT_NODES = 200


class CodeGraphStore:
    """SQLite-backed code knowledge graph with FTS5 search."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), timeout=10.0)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA cache_size=-8000")
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> CodeGraphStore:
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @property
    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("CodeGraphStore not opened. Call open() first.")
        return self._conn

    @property
    def connection(self) -> sqlite3.Connection:
        """Public access to the underlying SQLite connection for analysis modules."""
        return self._db

    def _init_schema(self) -> None:
        cursor = self._db.cursor()
        try:
            row = cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='_schema_version'"
            ).fetchone()
        except sqlite3.OperationalError:
            row = None

        if row is None:
            cursor.executescript(_SCHEMA_SQL)
            cursor.execute(
                "INSERT INTO _schema_version (version) VALUES (?)",
                (_SCHEMA_VERSION,),
            )
            self._db.commit()
            return

        version_row = cursor.execute("SELECT version FROM _schema_version").fetchone()
        current_version = version_row[0] if version_row else 0
        if current_version < _SCHEMA_VERSION:
            self._run_migrations(current_version)

    def _run_migrations(self, from_version: int) -> None:
        cursor = self._db.cursor()
        if from_version < 2:
            cursor.executescript("""
                CREATE INDEX IF NOT EXISTS idx_edges_target_kind ON edges(target_qualified, kind);
                CREATE INDEX IF NOT EXISTS idx_edges_source_kind ON edges(source_qualified, kind);
                CREATE INDEX IF NOT EXISTS idx_edges_file ON edges(file_path);
            """)
            try:
                cursor.executescript("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_edges_unique
                        ON edges(kind, source_qualified, target_qualified);
                """)
            except (sqlite3.OperationalError, sqlite3.IntegrityError):
                logger.warning("Edge dedup index creation failed (duplicates exist). Rebuilding edges table.")
                cursor.executescript("""
                    CREATE TABLE edges_new AS
                        SELECT e.* FROM edges e
                        INNER JOIN (
                            SELECT MAX(rowid) AS max_id
                            FROM edges
                            GROUP BY kind, source_qualified, target_qualified
                        ) keep ON e.rowid = keep.max_id;
                    DROP TABLE edges;
                    ALTER TABLE edges_new RENAME TO edges;
                """)
                cursor.executescript("""
                    CREATE UNIQUE INDEX idx_edges_unique ON edges(kind, source_qualified, target_qualified);
                    CREATE INDEX idx_edges_source ON edges(source_qualified);
                    CREATE INDEX idx_edges_target ON edges(target_qualified);
                    CREATE INDEX idx_edges_kind ON edges(kind);
                    CREATE INDEX idx_edges_target_kind ON edges(target_qualified, kind);
                    CREATE INDEX idx_edges_source_kind ON edges(source_qualified, kind);
                    CREATE INDEX idx_edges_file ON edges(file_path);
                """)
            cursor.execute("UPDATE _schema_version SET version = 2")
            self._db.commit()

    # ── Write operations ──

    def upsert_nodes(self, nodes: Sequence[GraphNode], file_hash: str = "") -> int:
        now = time.time()
        count = 0
        cursor = self._db.cursor()
        for node in nodes:
            cursor.execute(
                """INSERT INTO nodes
                   (kind, name, qualified_name, file_path, line_start, line_end,
                    language, parent_name, params, return_type, modifiers,
                    is_test, file_hash, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(qualified_name) DO UPDATE SET
                    kind=excluded.kind, name=excluded.name,
                    file_path=excluded.file_path, line_start=excluded.line_start,
                    line_end=excluded.line_end, language=excluded.language,
                    parent_name=excluded.parent_name, params=excluded.params,
                    return_type=excluded.return_type, modifiers=excluded.modifiers,
                    is_test=excluded.is_test, file_hash=excluded.file_hash,
                    updated_at=excluded.updated_at""",
                (
                    node.kind.value, node.name, node.qualified_name,
                    node.file_path, node.line_start, node.line_end,
                    node.language, node.parent_name, node.params,
                    node.return_type, node.modifiers, int(node.is_test),
                    file_hash, now,
                ),
            )
            count += 1
        self._db.commit()
        return count

    def upsert_edges(self, edges: Sequence[GraphEdge]) -> int:
        now = time.time()
        count = 0
        cursor = self._db.cursor()
        for edge in edges:
            cursor.execute(
                """INSERT INTO edges
                   (kind, source_qualified, target_qualified, file_path,
                    line, confidence, confidence_tier, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(kind, source_qualified, target_qualified) DO UPDATE SET
                    file_path=excluded.file_path, line=excluded.line,
                    confidence=excluded.confidence,
                    confidence_tier=excluded.confidence_tier,
                    updated_at=excluded.updated_at""",
                (
                    edge.kind.value, edge.source_qualified, edge.target_qualified,
                    edge.file_path, edge.line, edge.confidence,
                    edge.confidence_tier.value, now,
                ),
            )
            count += 1
        self._db.commit()
        return count

    def remove_file(self, file_path: str) -> None:
        cursor = self._db.cursor()
        cursor.execute("DELETE FROM edges WHERE file_path = ?", (file_path,))
        cursor.execute("DELETE FROM nodes WHERE file_path = ?", (file_path,))
        self._db.commit()

    def clear(self) -> None:
        cursor = self._db.cursor()
        cursor.execute("DELETE FROM edges")
        cursor.execute("DELETE FROM nodes")
        self._db.commit()

    # ── Read operations ──

    def get_file_hash(self, file_path: str) -> str | None:
        row = self._db.execute(
            "SELECT file_hash FROM nodes WHERE file_path = ? LIMIT 1",
            (file_path,),
        ).fetchone()
        return row["file_hash"] if row else None

    def node_count(self) -> int:
        row = self._db.execute("SELECT COUNT(*) AS cnt FROM nodes").fetchone()
        return row["cnt"]

    def edge_count(self) -> int:
        row = self._db.execute("SELECT COUNT(*) AS cnt FROM edges").fetchone()
        return row["cnt"]

    def file_count(self) -> int:
        row = self._db.execute(
            "SELECT COUNT(DISTINCT file_path) AS cnt FROM nodes"
        ).fetchone()
        return row["cnt"]

    def find_callers(
        self, qualified_name: str, *, max_results: int = 50
    ) -> list[dict[str, str | int]]:
        rows = self._db.execute(
            """SELECT e.kind, e.source_qualified, e.file_path, e.line, e.confidence
               FROM edges e
               WHERE e.target_qualified = ? AND e.kind IN ('CALLS', 'REFERENCES')
               ORDER BY e.confidence DESC
               LIMIT ?""",
            (qualified_name, max_results),
        ).fetchall()
        return [dict(r) for r in rows]

    def find_dependencies(
        self, qualified_name: str, *, max_results: int = 50
    ) -> list[dict[str, str | int]]:
        rows = self._db.execute(
            """SELECT e.kind, e.target_qualified, e.file_path, e.line, e.confidence
               FROM edges e
               WHERE e.source_qualified = ?
               ORDER BY e.confidence DESC
               LIMIT ?""",
            (qualified_name, max_results),
        ).fetchall()
        return [dict(r) for r in rows]

    def impact_radius(
        self,
        qualified_name: str,
        *,
        max_depth: int = MAX_IMPACT_DEPTH,
        max_nodes: int = MAX_IMPACT_NODES,
    ) -> ImpactResult:
        """BFS traversal to find all nodes affected by changes to the target."""
        visited: set[str] = {qualified_name}
        queue: list[tuple[str, int]] = [(qualified_name, 0)]
        affected: list[dict[str, str | int]] = []
        affected_files: set[str] = set()
        max_depth_reached = 0

        while queue and len(affected) < max_nodes:
            current, depth = queue.pop(0)
            if depth > max_depth:
                continue
            max_depth_reached = max(max_depth_reached, depth)

            rows = self._db.execute(
                """SELECT e.source_qualified, n.file_path, n.kind, n.name, n.line_start
                   FROM edges e
                   JOIN nodes n ON n.qualified_name = e.source_qualified
                   WHERE e.target_qualified = ?
                     AND e.kind IN ('CALLS', 'REFERENCES', 'INHERITS', 'IMPLEMENTS')""",
                (current,),
            ).fetchall()

            for row in rows:
                sq = row["source_qualified"]
                if sq in visited:
                    continue
                visited.add(sq)
                affected.append({
                    "qualified_name": sq,
                    "file_path": row["file_path"],
                    "kind": row["kind"],
                    "name": row["name"],
                    "line": row["line_start"],
                    "depth": depth + 1,
                })
                affected_files.add(row["file_path"])
                if depth + 1 < max_depth and len(affected) < max_nodes:
                    queue.append((sq, depth + 1))

        total_files = self.file_count()
        return ImpactResult(
            target=qualified_name,
            affected_nodes=affected,
            affected_files=sorted(affected_files),
            depth_reached=max_depth_reached,
            total_files_scanned=total_files,
        )

    def search_fts(
        self, query: str, *, max_results: int = 20
    ) -> list[dict[str, str | int]]:
        from myrm_agent_harness.utils.db.fts5 import sanitize_fts5_query

        safe_query = sanitize_fts5_query(query)
        if not safe_query.strip():
            return []
        try:
            rows = self._db.execute(
                """SELECT n.qualified_name, n.name, n.kind, n.file_path,
                          n.line_start, n.line_end,
                          rank AS score
                   FROM nodes_fts
                   JOIN nodes n ON n.id = nodes_fts.rowid
                   WHERE nodes_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (safe_query, max_results),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError as exc:
            logger.warning("FTS5 query failed: %s", exc)
            return []

    def get_stats(self) -> dict[str, int]:
        return {
            "nodes": self.node_count(),
            "edges": self.edge_count(),
            "files": self.file_count(),
        }

    @staticmethod
    def workspace_db_path(data_dir: Path, workspace_root: str) -> Path:
        workspace_hash = hashlib.sha256(workspace_root.encode()).hexdigest()[:16]
        return data_dir / "code_graph" / f"{workspace_hash}.db"
