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
    # b has degree 2 (a→b, b→c), log2-scaled value >= 1
    b_node = next(n for n in nodes if n["id"] == "b")
    assert b_node["val"] >= 1


def test_label_propagation_determinism():
    nodes = [{"id": f"node_{i}"} for i in range(20)]
    edges = [{"source": f"node_{i}", "target": f"node_{(i + 1) % 20}", "weight": 1.0} for i in range(20)]
    res1 = label_propagation(nodes, edges)
    res2 = label_propagation(nodes, edges)
    assert res1 == res2, "LPA must be strictly deterministic across consecutive executions"


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


def _add_pages(conn: sqlite3.Connection, *names: str) -> None:
    for name in names:
        conn.execute("INSERT INTO wiki_fts (concept_name, truth_content) VALUES (?, ?)", (name, f"Content {name}"))


def _add_edges(conn: sqlite3.Connection, *edges: tuple[str, str]) -> None:
    for source, target in edges:
        conn.execute("INSERT OR REPLACE INTO wiki_edges VALUES (?, ?, 3.0)", (source, target))


def test_cohesion_never_exceeds_one_for_mutually_linked_pages():
    conn = _create_test_db()
    _add_pages(conn, "a", "b", "c")
    _add_edges(conn, ("a", "b"), ("b", "a"), ("b", "c"), ("c", "b"), ("a", "c"), ("c", "a"))

    communities = compute_graph_insights(conn)["communities"]

    assert len(communities) == 1
    assert communities[0]["cohesion"] == 1.0
    conn.close()


def test_interim_raw_and_sidecar_entries_are_not_graph_nodes():
    conn = _create_test_db()
    _add_pages(conn, "a", "b", "raw:notes/meeting", "__sidecar__:L0:abc")
    _add_edges(conn, ("a", "b"))

    result = compute_graph_insights(conn)

    listed = {gap["node"] for gap in result["knowledge_gaps"]}
    assert listed == {"a", "b"}
    assert sum(community["size"] for community in result["communities"]) == 2
    conn.close()


def test_pseudo_and_unresolved_targets_do_not_count_as_connections():
    conn = _create_test_db()
    _add_pages(conn, "a", "b")
    _add_edges(conn, ("a", "b"), ("a", "system:crm"), ("a", "Unresolved Mention"))

    gaps = {gap["node"]: gap for gap in compute_graph_insights(conn)["knowledge_gaps"]}

    assert gaps["a"]["degree"] == 1
    conn.close()


def test_insights_cover_attached_public_indexes(tmp_path):
    public_db = tmp_path / "public.db"
    public = sqlite3.connect(public_db)
    public.execute("CREATE VIRTUAL TABLE wiki_fts USING fts5(concept_name, truth_content)")
    public.execute(
        "CREATE TABLE wiki_edges(source TEXT, target TEXT, weight REAL DEFAULT 1.0, PRIMARY KEY (source, target))"
    )
    public.execute("INSERT INTO wiki_fts (concept_name, truth_content) VALUES ('shared/guide', 'x')")
    public.execute("INSERT INTO wiki_edges VALUES ('shared/guide', 'local/page', 3.0)")
    public.commit()
    public.close()

    conn = _create_test_db()
    conn.execute("ATTACH DATABASE ? AS pub_0", (str(public_db),))
    _add_pages(conn, "local/page", "local/other")
    _add_edges(conn, ("local/page", "local/other"))

    communities = compute_graph_insights(conn)["communities"]

    assert sum(community["size"] for community in communities) == 3
    assert communities[0]["size"] == 3
    conn.close()


def test_each_gap_kind_has_its_own_quota():
    conn = _create_test_db()
    triangles = {"a": ("a1", "a2", "a3"), "b": ("b1", "b2", "b3"), "c": ("c1", "c2", "c3")}
    isolated = [f"iso{index:02d}" for index in range(40)]
    _add_pages(conn, "hub", *isolated, *(name for members in triangles.values() for name in members))
    for first, second, third in triangles.values():
        _add_edges(conn, (first, second), (second, third), (first, third), ("hub", first))

    gaps = compute_graph_insights(conn)["knowledge_gaps"]

    assert [gap["node"] for gap in gaps if gap["type"] == "bridge"] == ["hub"]
    assert len([gap for gap in gaps if gap["type"] == "isolated"]) == 15
    assert all(gap["degree"] == 0 for gap in gaps if gap["type"] == "isolated")
    conn.close()


def test_community_lists_hubs_first_and_largest_community_first():
    conn = _create_test_db()
    _add_pages(conn, "centre", "leaf1", "leaf2", "leaf3", "x", "y")
    _add_edges(conn, ("centre", "leaf1"), ("centre", "leaf2"), ("centre", "leaf3"), ("x", "y"))

    communities = compute_graph_insights(conn)["communities"]

    assert [community["size"] for community in communities] == [4, 2]
    assert communities[0]["members"][0] == "centre"
    conn.close()


def test_lone_pages_are_gaps_not_clusters():
    conn = _create_test_db()
    _add_pages(conn, "a", "b", "alone1", "alone2")
    _add_edges(conn, ("a", "b"))

    result = compute_graph_insights(conn)

    assert [sorted(community["members"]) for community in result["communities"]] == [["a", "b"]]
    assert {gap["node"] for gap in result["knowledge_gaps"]} >= {"alone1", "alone2"}
    conn.close()
