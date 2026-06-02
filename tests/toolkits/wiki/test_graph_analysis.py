"""Tests for graph_analysis module - LPA community detection and graph insights."""

import sqlite3

from myrm_agent_harness.toolkits.wiki.retrieval.graph_analysis import (
    compute_graph_insights,
    enrich_graph_with_communities,
    label_propagation,
)


def test_label_propagation_single_community():
    nodes = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    edges = [
        {"source": "a", "target": "b", "weight": 1.0},
        {"source": "b", "target": "c", "weight": 1.0},
        {"source": "a", "target": "c", "weight": 1.0},
    ]
    labels = label_propagation(nodes, edges)
    assert len(labels) == 3
    assert labels["a"] == labels["b"] == labels["c"]


def test_label_propagation_two_communities():
    nodes = [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}]
    edges = [
        {"source": "a", "target": "b", "weight": 1.0},
        {"source": "c", "target": "d", "weight": 1.0},
    ]
    labels = label_propagation(nodes, edges)
    assert labels["a"] == labels["b"]
    assert labels["c"] == labels["d"]
    assert labels["a"] != labels["c"]


def test_label_propagation_isolated_node():
    nodes = [{"id": "a"}, {"id": "b"}, {"id": "isolated"}]
    edges = [{"source": "a", "target": "b", "weight": 1.0}]
    labels = label_propagation(nodes, edges)
    assert len(labels) == 3
    assert "isolated" in labels


def test_enrich_graph_with_communities():
    nodes = [{"id": "a", "group": 0}, {"id": "b", "group": 0}, {"id": "c", "group": 0}]
    edges = [
        {"source": "a", "target": "b", "weight": 1.0},
        {"source": "b", "target": "c", "weight": 1.0},
    ]
    enrich_graph_with_communities(nodes, edges)
    for node in nodes:
        assert "group" in node
        assert "val" in node
        assert node["val"] >= 1
    # b has degree 2 (a→b, b→c)
    b_node = next(n for n in nodes if n["id"] == "b")
    assert b_node["val"] == 2


def test_enrich_graph_empty():
    nodes: list[dict] = []
    edges: list[dict] = []
    enrich_graph_with_communities(nodes, edges)
    assert nodes == []


def _create_test_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE VIRTUAL TABLE wiki_fts USING fts5(
            concept_name, truth_content,
            tokenize="unicode61 remove_diacritics 1"
        )
    """)
    conn.execute("""
        CREATE TABLE wiki_edges(
            source TEXT, target TEXT, weight REAL DEFAULT 1.0,
            PRIMARY KEY (source, target)
        )
    """)
    return conn


def test_compute_graph_insights_empty():
    conn = _create_test_db()
    result = compute_graph_insights(conn)
    assert result == {"unexpected_connections": [], "knowledge_gaps": [], "communities": []}
    conn.close()


def test_compute_graph_insights_with_data():
    conn = _create_test_db()
    for name in ["A", "B", "C", "D", "E"]:
        conn.execute("INSERT INTO wiki_fts (concept_name, truth_content) VALUES (?, ?)", (name, f"Content {name}"))
    # A-B-C form one cluster, D-E form another, A-D is cross-community bridge
    conn.execute("INSERT INTO wiki_edges VALUES ('A', 'B', 3.0)")
    conn.execute("INSERT INTO wiki_edges VALUES ('B', 'C', 3.0)")
    conn.execute("INSERT INTO wiki_edges VALUES ('A', 'C', 3.0)")
    conn.execute("INSERT INTO wiki_edges VALUES ('D', 'E', 3.0)")
    conn.execute("INSERT INTO wiki_edges VALUES ('A', 'D', 1.0)")
    conn.commit()

    result = compute_graph_insights(conn)
    assert "unexpected_connections" in result
    assert "knowledge_gaps" in result
    assert "communities" in result
    assert len(result["communities"]) >= 1
    conn.close()


def test_compute_graph_insights_isolated_nodes():
    conn = _create_test_db()
    for name in ["X", "Y", "Z"]:
        conn.execute("INSERT INTO wiki_fts (concept_name, truth_content) VALUES (?, ?)", (name, f"Content {name}"))
    conn.execute("INSERT INTO wiki_edges VALUES ('X', 'Y', 3.0)")
    conn.commit()

    result = compute_graph_insights(conn)
    gaps = result["knowledge_gaps"]
    isolated = [g for g in gaps if g["type"] == "isolated"]
    assert any(g["node"] == "Z" for g in isolated)
    conn.close()
