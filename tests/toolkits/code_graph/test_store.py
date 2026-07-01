"""Tests for code_graph store — UNIQUE dedup, composite indexes, migrations."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.code_graph.store import (
    CodeGraphStore,
    ConfidenceTier,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)


@pytest.fixture
def store(tmp_path: Path) -> CodeGraphStore:
    db_path = tmp_path / "test.db"
    s = CodeGraphStore(db_path)
    s.open()
    yield s
    s.close()


def _make_node(name: str, file_path: str = "src/main.py") -> GraphNode:
    return GraphNode(
        kind=NodeKind.FUNCTION,
        name=name,
        qualified_name=f"{file_path}::{name}",
        file_path=file_path,
        line_start=1,
        line_end=10,
        language="python",
    )


def _make_edge(
    source: str,
    target: str,
    kind: EdgeKind = EdgeKind.CALLS,
    file_path: str = "src/main.py",
) -> GraphEdge:
    return GraphEdge(
        kind=kind,
        source_qualified=source,
        target_qualified=target,
        file_path=file_path,
        line=5,
    )


class TestSchemaInit:
    def test_creates_tables_on_open(self, store: CodeGraphStore) -> None:
        assert store.node_count() == 0
        assert store.edge_count() == 0

    def test_schema_version_is_2(self, store: CodeGraphStore) -> None:
        row = store.connection.execute("SELECT version FROM _schema_version").fetchone()
        assert row["version"] == 2

    def test_unique_constraint_on_edges(self, store: CodeGraphStore) -> None:
        row = store.connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='edges'"
        ).fetchone()
        assert "UNIQUE" in row["sql"]


class TestUpsertEdgesDedup:
    def test_duplicate_edges_are_deduplicated(self, store: CodeGraphStore) -> None:
        nodes = [_make_node("foo"), _make_node("bar")]
        store.upsert_nodes(nodes)

        edge = _make_edge("src/main.py::foo", "src/main.py::bar")
        store.upsert_edges([edge])
        store.upsert_edges([edge])
        store.upsert_edges([edge])

        assert store.edge_count() == 1

    def test_upsert_edge_updates_metadata(self, store: CodeGraphStore) -> None:
        nodes = [_make_node("foo"), _make_node("bar")]
        store.upsert_nodes(nodes)

        edge_v1 = GraphEdge(
            kind=EdgeKind.CALLS,
            source_qualified="src/main.py::foo",
            target_qualified="src/main.py::bar",
            file_path="src/main.py",
            line=5,
            confidence=0.5,
            confidence_tier=ConfidenceTier.INFERRED,
        )
        store.upsert_edges([edge_v1])

        edge_v2 = GraphEdge(
            kind=EdgeKind.CALLS,
            source_qualified="src/main.py::foo",
            target_qualified="src/main.py::bar",
            file_path="src/main.py",
            line=10,
            confidence=1.0,
            confidence_tier=ConfidenceTier.RESOLVED,
        )
        store.upsert_edges([edge_v2])

        assert store.edge_count() == 1
        row = store.connection.execute(
            "SELECT line, confidence, confidence_tier FROM edges"
        ).fetchone()
        assert row["line"] == 10
        assert row["confidence"] == 1.0
        assert row["confidence_tier"] == "RESOLVED"

    def test_different_edge_kinds_are_separate(self, store: CodeGraphStore) -> None:
        nodes = [_make_node("foo"), _make_node("bar")]
        store.upsert_nodes(nodes)

        edge_call = _make_edge("src/main.py::foo", "src/main.py::bar", EdgeKind.CALLS)
        edge_ref = _make_edge("src/main.py::foo", "src/main.py::bar", EdgeKind.REFERENCES)
        store.upsert_edges([edge_call, edge_ref])

        assert store.edge_count() == 2


class TestCompositeIndexes:
    def test_indexes_exist(self, store: CodeGraphStore) -> None:
        rows = store.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        index_names = {row["name"] for row in rows}

        assert "idx_edges_target_kind" in index_names
        assert "idx_edges_source_kind" in index_names
        assert "idx_edges_file" in index_names


class TestMigrationV1ToV2:
    def test_migration_creates_indexes_and_deduplicates(self, tmp_path: Path) -> None:
        """Simulate a v1 database with duplicate edges, upgrade to v2."""
        db_path = tmp_path / "v1.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE _schema_version (version INTEGER NOT NULL);
            INSERT INTO _schema_version (version) VALUES (1);

            CREATE TABLE nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL, name TEXT NOT NULL,
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
            CREATE INDEX idx_nodes_file ON nodes(file_path);
            CREATE INDEX idx_nodes_kind ON nodes(kind);
            CREATE INDEX idx_nodes_name ON nodes(name);

            CREATE TABLE edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                source_qualified TEXT NOT NULL,
                target_qualified TEXT NOT NULL,
                file_path TEXT NOT NULL,
                line INTEGER NOT NULL DEFAULT 0,
                confidence REAL NOT NULL DEFAULT 1.0,
                confidence_tier TEXT NOT NULL DEFAULT 'EXTRACTED',
                updated_at REAL NOT NULL
            );
            CREATE INDEX idx_edges_source ON edges(source_qualified);
            CREATE INDEX idx_edges_target ON edges(target_qualified);
            CREATE INDEX idx_edges_kind ON edges(kind);

            CREATE VIRTUAL TABLE nodes_fts USING fts5(
                name, qualified_name, file_path,
                content=nodes, content_rowid=id,
                tokenize='porter unicode61'
            );
        """)

        conn.executemany(
            "INSERT INTO edges (kind, source_qualified, target_qualified, file_path, line, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("CALLS", "a::foo", "a::bar", "a.py", 1, 100.0),
                ("CALLS", "a::foo", "a::bar", "a.py", 2, 200.0),
                ("CALLS", "a::foo", "a::bar", "a.py", 3, 300.0),
            ],
        )
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 3
        conn.close()

        store = CodeGraphStore(db_path)
        store.open()

        assert store.edge_count() == 1

        row = store.connection.execute("SELECT version FROM _schema_version").fetchone()
        assert row[0] == 2

        rows = store.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        index_names = {row[0] for row in rows}
        assert "idx_edges_target_kind" in index_names
        assert "idx_edges_source_kind" in index_names
        assert "idx_edges_file" in index_names

        store.close()


class TestQueryOperations:
    def test_find_callers(self, store: CodeGraphStore) -> None:
        nodes = [_make_node("foo"), _make_node("bar")]
        store.upsert_nodes(nodes)
        store.upsert_edges([_make_edge("src/main.py::foo", "src/main.py::bar")])

        callers = store.find_callers("src/main.py::bar")
        assert len(callers) == 1
        assert callers[0]["source_qualified"] == "src/main.py::foo"

    def test_find_dependencies(self, store: CodeGraphStore) -> None:
        nodes = [_make_node("foo"), _make_node("bar")]
        store.upsert_nodes(nodes)
        store.upsert_edges([_make_edge("src/main.py::foo", "src/main.py::bar")])

        deps = store.find_dependencies("src/main.py::foo")
        assert len(deps) == 1
        assert deps[0]["target_qualified"] == "src/main.py::bar"

    def test_impact_radius(self, store: CodeGraphStore) -> None:
        nodes = [_make_node("a"), _make_node("b"), _make_node("c")]
        store.upsert_nodes(nodes)
        store.upsert_edges([
            _make_edge("src/main.py::b", "src/main.py::a"),
            _make_edge("src/main.py::c", "src/main.py::b"),
        ])

        result = store.impact_radius("src/main.py::a")
        assert len(result.affected_nodes) >= 1
        names = {n["qualified_name"] for n in result.affected_nodes}
        assert "src/main.py::b" in names

    def test_remove_file(self, store: CodeGraphStore) -> None:
        nodes = [_make_node("foo"), _make_node("bar", "other.py")]
        store.upsert_nodes(nodes)
        store.upsert_edges([_make_edge("src/main.py::foo", "other.py::bar")])

        store.remove_file("src/main.py")
        assert store.node_count() == 1

    def test_fts_search(self, store: CodeGraphStore) -> None:
        nodes = [_make_node("calculate_total"), _make_node("get_user")]
        store.upsert_nodes(nodes)

        results = store.search_fts("calculate")
        assert len(results) >= 1
        assert any("calculate_total" in r["name"] for r in results)

    def test_get_stats(self, store: CodeGraphStore) -> None:
        nodes = [_make_node("foo"), _make_node("bar")]
        store.upsert_nodes(nodes)
        store.upsert_edges([_make_edge("src/main.py::foo", "src/main.py::bar")])

        stats = store.get_stats()
        assert stats["nodes"] == 2
        assert stats["edges"] == 1
        assert stats["files"] == 1

    def test_fts_empty_query_returns_empty(self, store: CodeGraphStore) -> None:
        store.upsert_nodes([_make_node("foo")])
        assert store.search_fts("") == []
        assert store.search_fts("   ") == []

    def test_impact_radius_max_depth(self, store: CodeGraphStore) -> None:
        """Depth > max_depth should be skipped."""
        nodes = [_make_node(f"n{i}") for i in range(5)]
        store.upsert_nodes(nodes)
        store.upsert_edges([
            _make_edge("src/main.py::n1", "src/main.py::n0"),
            _make_edge("src/main.py::n2", "src/main.py::n1"),
            _make_edge("src/main.py::n3", "src/main.py::n2"),
            _make_edge("src/main.py::n4", "src/main.py::n3"),
        ])

        result = store.impact_radius("src/main.py::n0", max_depth=1)
        assert result.depth_reached <= 1
        for n in result.affected_nodes:
            assert n["depth"] <= 1

    def test_impact_radius_visited_dedup(self, store: CodeGraphStore) -> None:
        """Cycles should not cause infinite traversal."""
        nodes = [_make_node("x"), _make_node("y")]
        store.upsert_nodes(nodes)
        store.upsert_edges([
            _make_edge("src/main.py::y", "src/main.py::x"),
            _make_edge("src/main.py::x", "src/main.py::y"),
        ])

        result = store.impact_radius("src/main.py::x")
        assert len(result.affected_nodes) == 1

    def test_get_file_hash_existing(self, store: CodeGraphStore) -> None:
        store.upsert_nodes([_make_node("foo")], file_hash="abc123")
        assert store.get_file_hash("src/main.py") == "abc123"

    def test_get_file_hash_nonexistent(self, store: CodeGraphStore) -> None:
        assert store.get_file_hash("nonexistent.py") is None

    def test_clear(self, store: CodeGraphStore) -> None:
        store.upsert_nodes([_make_node("foo"), _make_node("bar")])
        store.upsert_edges([_make_edge("src/main.py::foo", "src/main.py::bar")])
        assert store.node_count() == 2
        store.clear()
        assert store.node_count() == 0
        assert store.edge_count() == 0


class TestContextManager:
    def test_context_manager_opens_and_closes(self, tmp_path: Path) -> None:
        db_path = tmp_path / "ctx.db"
        with CodeGraphStore(db_path) as store:
            assert store.node_count() == 0
            store.upsert_nodes([_make_node("foo")])
            assert store.node_count() == 1

    def test_access_before_open_raises(self, tmp_path: Path) -> None:
        store = CodeGraphStore(tmp_path / "unopened.db")
        with pytest.raises(RuntimeError, match="not opened"):
            store.node_count()


class TestWorkspaceDbPath:
    def test_deterministic_path(self) -> None:
        p1 = CodeGraphStore.workspace_db_path(Path("/data"), "/workspace")
        p2 = CodeGraphStore.workspace_db_path(Path("/data"), "/workspace")
        assert p1 == p2

    def test_different_workspaces_different_paths(self) -> None:
        p1 = CodeGraphStore.workspace_db_path(Path("/data"), "/ws-a")
        p2 = CodeGraphStore.workspace_db_path(Path("/data"), "/ws-b")
        assert p1 != p2
