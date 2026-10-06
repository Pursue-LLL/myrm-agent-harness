# [POS] tests/toolkits/memory/test_graph_rrf_retriever.py
# [INPUT] SQLiteGraphMemoryStore, ReciprocalRankFusionEngine, DualChannelRRFRetriever, EntityNode, RelationEdge, VectorHit, GraphHit, RRFConfig
# [OUTPUT] pytest test suite for graph_rrf engine

"""Unit and integration tests for Hybrid Knowledge Graph & Vector RRF Memory Engine."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.memory.graph_rrf import (
    DualChannelRRFRetriever,
    EntityNode,
    GraphHit,
    ReciprocalRankFusionEngine,
    RelationEdge,
    RRFConfig,
    SQLiteGraphMemoryStore,
    VectorHit,
)


@pytest.fixture
def memory_store() -> SQLiteGraphMemoryStore:
    """Fixture providing an in-memory graph store."""
    store = SQLiteGraphMemoryStore(":memory:")
    yield store
    store.close()


def test_sqlite_graph_store_crud(memory_store: SQLiteGraphMemoryStore) -> None:
    """Verify entity, relation, and memory association persistence."""
    node_a = EntityNode(
        id="ent-1",
        name="Alice",
        entity_type="person",
        properties={"role": "architect"},
    )
    node_b = EntityNode(
        id="ent-2",
        name="Aurora",
        entity_type="project",
        properties={"status": "active"},
    )
    edge = RelationEdge(
        id="rel-1",
        source_id="ent-1",
        target_id="ent-2",
        relation_type="owns",
        weight=1.0,
    )

    memory_store.add_node(node_a)
    memory_store.add_node(node_b)
    memory_store.add_edge(edge)

    fetched_a = memory_store.get_node("ent-1")
    assert fetched_a is not None
    assert fetched_a.name == "Alice"
    assert fetched_a.properties.get("role") == "architect"

    by_name = memory_store.find_node_by_name("aurora")
    assert by_name is not None
    assert by_name.id == "ent-2"

    memory_store.associate_memory(
        "mem-101", "ent-1", "Alice designed Aurora architecture."
    )
    assocs = memory_store.get_associated_memories(["ent-1"])
    assert assocs == ["mem-101"]
    content = memory_store.get_memory_content("mem-101")
    assert "Alice designed Aurora" in content


def test_sqlite_graph_store_bfs_traversal(
    memory_store: SQLiteGraphMemoryStore,
) -> None:
    """Verify 1-hop and 2-hop BFS traversal and path generation."""
    # A -> B -> C -> D
    nodes = [
        EntityNode(id="n-a", name="NodeA", entity_type="T"),
        EntityNode(id="n-b", name="NodeB", entity_type="T"),
        EntityNode(id="n-c", name="NodeC", entity_type="T"),
        EntityNode(id="n-d", name="NodeD", entity_type="T"),
    ]
    for n in nodes:
        memory_store.add_node(n)

    memory_store.add_edge(
        RelationEdge(
            id="e-ab",
            source_id="n-a",
            target_id="n-b",
            relation_type="leads_to",
        )
    )
    memory_store.add_edge(
        RelationEdge(
            id="e-bc",
            source_id="n-b",
            target_id="n-c",
            relation_type="leads_to",
        )
    )
    memory_store.add_edge(
        RelationEdge(
            id="e-cd",
            source_id="n-c",
            target_id="n-d",
            relation_type="leads_to",
        )
    )

    memory_store.associate_memory("mem-c", "n-c", "Content at Node C")
    memory_store.associate_memory("mem-d", "n-d", "Content at Node D")

    # 1 hop traversal from NodeA: should only reach NodeB
    res_1hop = memory_store.traverse(["n-a"], max_hops=1)
    reached_1hop = {n.id for n in res_1hop.nodes}
    assert reached_1hop == {"n-a", "n-b"}
    assert "mem-c" not in res_1hop.associated_memory_ids

    # 2 hop traversal from NodeA: reaches NodeB and NodeC
    res_2hop = memory_store.traverse(["n-a"], max_hops=2)
    reached_2hop = {n.id for n in res_2hop.nodes}
    assert reached_2hop == {"n-a", "n-b", "n-c"}
    assert "mem-c" in res_2hop.associated_memory_ids
    assert "mem-d" not in res_2hop.associated_memory_ids


def test_sqlite_graph_store_cycle_protection(
    memory_store: SQLiteGraphMemoryStore,
) -> None:
    """Verify traversal handles cyclic graph topologies without recursion or deadlock."""
    # Cyclic loop: C1 -> C2 -> C3 -> C1
    for cid in ["c1", "c2", "c3"]:
        memory_store.add_node(
            EntityNode(id=cid, name=f"CycleNode-{cid}", entity_type="C")
        )

    memory_store.add_edge(
        RelationEdge(
            id="ec-1", source_id="c1", target_id="c2", relation_type="loops"
        )
    )
    memory_store.add_edge(
        RelationEdge(
            id="ec-2", source_id="c2", target_id="c3", relation_type="loops"
        )
    )
    memory_store.add_edge(
        RelationEdge(
            id="ec-3", source_id="c3", target_id="c1", relation_type="loops"
        )
    )

    res = memory_store.traverse(["c1"], max_hops=5)
    assert len(res.nodes) == 3
    assert {n.id for n in res.nodes} == {"c1", "c2", "c3"}


def test_rrf_fusion_mathematics() -> None:
    """Verify reciprocal rank fusion scoring formula 1 / (k + rank)."""
    engine = ReciprocalRankFusionEngine()

    # Score for rank 1 with k=60: 1 / 61 ≈ 0.016393
    s1 = engine.compute_single_score(rank=1, k=60, weight=1.0)
    assert abs(s1 - (1.0 / 61.0)) < 1e-6

    # Score for rank 2 with k=60: 1 / 62 ≈ 0.016129
    s2 = engine.compute_single_score(rank=2, k=60, weight=1.0)
    assert abs(s2 - (1.0 / 62.0)) < 1e-6
    assert s1 > s2

    vec_hits = [
        VectorHit(
            memory_id="m-both", content="Shared memory", score=0.9, rank=1
        ),
        VectorHit(
            memory_id="m-vec-only",
            content="Vector exclusive",
            score=0.8,
            rank=2,
        ),
    ]
    graph_hits = [
        GraphHit(
            memory_id="m-both",
            entity_id="e1",
            content="Shared memory",
            hop=1,
            path=["e0->(ref)->e1"],
            score=0.5,
            rank=1,
        ),
        GraphHit(
            memory_id="m-graph-only",
            entity_id="e2",
            content="Graph exclusive",
            hop=2,
            path=["e0->(ref)->e2"],
            score=0.33,
            rank=2,
        ),
    ]

    config = RRFConfig(k=60, top_k=5)
    fused = engine.fuse(vec_hits, graph_hits, config=config)

    # m-both should rank highest because it hits both channels
    assert len(fused) == 3
    assert fused[0].memory_id == "m-both"
    assert "vector" in fused[0].hit_sources
    assert "graph" in fused[0].hit_sources
    expected_both_score = (1.0 / 61.0) + (1.0 / 61.0)
    assert abs(fused[0].fused_score - expected_both_score) < 1e-5


def test_dual_channel_retriever_multi_hop_supremacy(
    memory_store: SQLiteGraphMemoryStore,
) -> None:
    """End-to-end test verifying multi-hop knowledge graph lifts relevant long-chain facts."""
    # Build Multi-Hop Knowledge Topology:
    # Alice -> (architect_of) -> Project-Nexus -> (governed_by) -> Director-Chen
    ent_alice = EntityNode(id="e-alice", name="Alice", entity_type="person")
    ent_nexus = EntityNode(
        id="e-nexus", name="Project-Nexus", entity_type="project"
    )
    ent_chen = EntityNode(
        id="e-chen", name="Director-Chen", entity_type="person"
    )

    memory_store.add_node(ent_alice)
    memory_store.add_node(ent_nexus)
    memory_store.add_node(ent_chen)

    memory_store.add_edge(
        RelationEdge(
            id="r1",
            source_id="e-alice",
            target_id="e-nexus",
            relation_type="architect_of",
        )
    )
    memory_store.add_edge(
        RelationEdge(
            id="r2",
            source_id="e-nexus",
            target_id="e-chen",
            relation_type="governed_by",
        )
    )

    # Associate memories:
    # mem-distractor: Has superficial word match with query, but has zero knowledge graph relation
    # mem-nexus: 1-hop fact
    # mem-chen: 2-hop causal fact ("All Project-Nexus budget decisions go to Director-Chen")
    memory_store.associate_memory(
        "mem-nexus",
        "e-nexus",
        "Alice founded Project-Nexus to rebuild our core pipeline.",
    )
    memory_store.associate_memory(
        "mem-chen",
        "e-chen",
        "Director-Chen holds the ultimate budget approval authority over Project-Nexus.",
    )

    # Mock Vector search: superficial word match ranks distractor first, but misses 2-hop fact mem-chen
    def mock_vector_search(query: str, top_k: int) -> list[VectorHit]:
        return [
            VectorHit(
                memory_id="mem-distractor",
                content="Alice usually enjoys espresso during project standups.",
                score=0.95,
                rank=1,
            ),
            VectorHit(
                memory_id="mem-nexus",
                content="Alice founded Project-Nexus to rebuild our core pipeline.",
                score=0.75,
                rank=2,
            ),
        ]

    retriever = DualChannelRRFRetriever(
        graph_store=memory_store,
        vector_search_fn=mock_vector_search,
        config=RRFConfig(k=60, max_graph_hops=2, top_k=5),
    )

    # Query asking about Alice's project governance
    query = "Who has budget approval authority over Alice's project?"
    fused_results = retriever.search(query=query, seed_entity_names=["Alice"])

    # 1. mem-chen (2-hop) must be successfully retrieved via graph traversal despite absent in vector search
    retrieved_ids = [r.memory_id for r in fused_results]
    assert "mem-chen" in retrieved_ids
    assert "mem-nexus" in retrieved_ids

    # 2. mem-nexus is present in BOTH channels, so its RRF score surpasses superficial distractor
    assert fused_results[0].memory_id == "mem-nexus"
    assert set(fused_results[0].hit_sources) == {"vector", "graph"}

    chen_hit = next(r for r in fused_results if r.memory_id == "mem-chen")
    assert "graph" in chen_hit.hit_sources
    assert chen_hit.graph_rank is not None
    assert chen_hit.vector_rank is None


def test_dual_channel_fallback_lexical_seeds(
    memory_store: SQLiteGraphMemoryStore,
) -> None:
    """Verify retriever extracts seed entities automatically when not explicitly provided."""
    memory_store.add_node(
        EntityNode(id="e-quantum", name="QuantumDB", entity_type="system")
    )
    memory_store.associate_memory(
        "mem-q1", "e-quantum", "QuantumDB stores graph state."
    )

    retriever = DualChannelRRFRetriever(
        graph_store=memory_store,
        vector_search_fn=None,
        config=RRFConfig(k=60, top_k=5),
    )

    # Seeds not explicitly passed, extracted from query text
    results = retriever.search(query="How does QuantumDB handle queries?")
    assert len(results) == 1
    assert results[0].memory_id == "mem-q1"
    assert "graph" in results[0].hit_sources
