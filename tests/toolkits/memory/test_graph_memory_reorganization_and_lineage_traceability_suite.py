"""Unit tests for Graph Memory Reorganization and Lineage Traceability Suite in Harness.

[POS]
Harness 框架记忆图谱重组与演化溯源链单元测试套件。
端到端验证多维语义边自动识别补齐、非破坏性演化（SUPERSEDES）、前世今生溯源轨迹追踪与版本回滚机制。
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory import (
    GraphMemoryReorganizationEngine,
    GraphRelationType,
    MemoryGraphNode,
    MemoryLineageTracker,
    MemoryNodeStatus,
)


def test_multi_relational_detection_and_batch_reorganization() -> None:
    """Verify that multi-relational contradiction and subsumption edges are detected and wired."""
    tracker = MemoryLineageTracker()
    engine = GraphMemoryReorganizationEngine(tracker=tracker)

    # 1. Contradictory nodes: same subject & predicate, conflicting object
    node_tw = MemoryGraphNode(
        node_id="node_tw_1",
        lineage_root_id="root_style",
        version=1,
        subject="User UI Styling",
        predicate="mandates",
        object_value="TailwindCSS atomic utility classes",
        content="User UI Styling mandates TailwindCSS atomic utility classes",
    )
    node_no_tw = MemoryGraphNode(
        node_id="node_tw_2",
        lineage_root_id="root_style_2",
        version=1,
        subject="User UI Styling",
        predicate="mandates",
        object_value="Native CSS Modules strictly without utility classes",
        content="User UI Styling mandates Native CSS Modules strictly without utility classes",
    )

    tracker.register_node(node_tw)
    tracker.register_node(node_no_tw)

    # Run batch reorganization
    report = engine.run_reorganization_batch(min_confidence=0.8)

    assert report.analyzed_nodes_count == 2
    assert report.created_edges_count >= 1
    assert len(report.edges) >= 1

    edges = tracker.list_all_edges()
    assert len(edges) >= 1
    conf_edges = [e for e in edges if e.relation_type == GraphRelationType.CONTRADICTION]
    assert len(conf_edges) == 1
    assert {conf_edges[0].source_node_id, conf_edges[0].target_node_id} == {"node_tw_1", "node_tw_2"}


def test_non_destructive_evolution_supersedes() -> None:
    """Verify that updating a node creates a v2 active node and supersedes the v1 node without physical deletion."""
    tracker = MemoryLineageTracker()
    engine = GraphMemoryReorganizationEngine(tracker=tracker)

    v1_node = MemoryGraphNode(
        node_id="pref_backend_v1",
        lineage_root_id="pref_backend_root",
        version=1,
        subject="Backend Architecture",
        predicate="framework_choice",
        object_value="Flask microframework",
        content="Backend Architecture framework choice is Flask microframework",
        confidence=0.85,
    )
    tracker.register_node(v1_node)

    # Evolve to FastAPI v2
    new_v2_spec = MemoryGraphNode(
        node_id="pref_backend_v2",
        lineage_root_id="",
        version=0,
        subject="Backend Architecture",
        predicate="framework_choice",
        object_value="FastAPI async framework",
        content="Backend Architecture framework choice upgraded to FastAPI async framework",
        confidence=0.98,
    )

    old_res, new_res, sup_edge = engine.record_evolution(
        superseded_node_id="pref_backend_v1",
        new_node=new_v2_spec,
        rationale="2026 upgrade for modern OpenAPI validation and async performance",
    )

    # 1. Assert old node status is SUPERSEDED and retained
    assert old_res.status == MemoryNodeStatus.SUPERSEDED
    assert old_res.version == 1
    persisted_old = tracker.get_node("pref_backend_v1")
    assert persisted_old is not None
    assert persisted_old.status == MemoryNodeStatus.SUPERSEDED

    # 2. Assert new node is ACTIVE, version is 2, shares same lineage root
    assert new_res.status == MemoryNodeStatus.ACTIVE
    assert new_res.version == 2
    assert new_res.lineage_root_id == "pref_backend_root"

    # 3. Assert supersedes edge connects v2 -> v1
    assert sup_edge.relation_type == GraphRelationType.SUPERSEDES
    assert sup_edge.source_node_id == "pref_backend_v2"
    assert sup_edge.target_node_id == "pref_backend_v1"

    # 4. Tracker active query should only return v2
    active_nodes = tracker.list_active_nodes(subject="Backend Architecture")
    assert len(active_nodes) == 1
    assert active_nodes[0].node_id == "pref_backend_v2"


def test_lineage_trail_trace_and_rollback() -> None:
    """Verify multi-generation evolution trace (v1 -> v2 -> v3) and version rollback."""
    tracker = MemoryLineageTracker()
    engine = GraphMemoryReorganizationEngine(tracker=tracker)

    # Generation 1
    v1 = MemoryGraphNode(
        node_id="db_node_v1",
        lineage_root_id="db_root",
        version=1,
        subject="Database Storage",
        predicate="engine",
        object_value="Plain SQLite file",
        content="Database Storage engine is Plain SQLite file",
    )
    tracker.register_node(v1)

    # Generation 2
    v2_spec = MemoryGraphNode(
        node_id="db_node_v2",
        lineage_root_id="",
        version=0,
        subject="Database Storage",
        predicate="engine",
        object_value="SQLite with WAL mode and memory cache",
        content="Database Storage engine upgraded to SQLite with WAL mode and memory cache",
    )
    engine.record_evolution("db_node_v1", v2_spec, "WAL mode concurrency improvement")

    # Generation 3
    v3_spec = MemoryGraphNode(
        node_id="db_node_v3",
        lineage_root_id="",
        version=0,
        subject="Database Storage",
        predicate="engine",
        object_value="Dual-track Hybrid: SQLite metadata + Qdrant vector store",
        content="Database Storage engine evolved to Dual-track Hybrid: SQLite metadata + Qdrant vector store",
    )
    engine.record_evolution("db_node_v2", v3_spec, "Integrated dense vector search")

    # Trace lineage trail from v3
    trail = tracker.trace_trail("db_node_v3")
    assert trail.lineage_root_id == "db_root"
    assert trail.target_node.version == 3
    assert trail.depth == 2  # v3 -> v2 -> v1
    assert len(trail.ancestor_nodes) == 2
    ancestor_ids = [a.node_id for a in trail.ancestor_nodes]
    assert "db_node_v2" in ancestor_ids
    assert "db_node_v1" in ancestor_ids

    # Rollback/revert to historical version 1
    reverted_old, new_active_v4 = tracker.revert_to_version(
        historical_node_id="db_node_v1",
        new_node_id="db_node_v4",
        rationale="Rollback to plain SQLite file format",
    )
    assert new_active_v4.version == 4
    assert new_active_v4.status == MemoryNodeStatus.ACTIVE
    assert new_active_v4.content == "Database Storage engine is Plain SQLite file"
    assert reverted_old.node_id == "db_node_v3"
    assert reverted_old.status == MemoryNodeStatus.REVERTED

