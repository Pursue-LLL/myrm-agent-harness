"""Tests for Knowledge Graph and Vector RRF Agent Tool and MemoryManager runtime integration.

[INPUT]
- toolkits.memory.graph_rrf::SQLiteGraphMemoryStore, DualChannelRRFRetriever, EntityNode, RelationEdge
- toolkits.memory.graph_rrf.tool::create_graph_rrf_search_tool, HybridGraphRRFSearchInput
- toolkits.memory.manager::MemoryManager, MemoryConfig

[OUTPUT]
- Pytest test cases verifying Agent runtime consumption of Graph-Vector RRF search tool.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.tools import BaseTool

from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.graph_rrf import (
    DualChannelRRFRetriever,
    EntityNode,
    RelationEdge,
    SQLiteGraphMemoryStore,
    VectorHit,
    create_graph_rrf_search_tool,
)
from myrm_agent_harness.toolkits.memory.manager import MemoryManager


@pytest.fixture
def populated_graph_store(tmp_path: Path) -> SQLiteGraphMemoryStore:
    db_file = tmp_path / "test_graph_memory.db"
    store = SQLiteGraphMemoryStore(db_path=db_file)

    # Populate entity nodes
    store.add_node(
        EntityNode(
            id="person:alice",
            name="Alice",
            entity_type="PERSON",
            properties={"role": "Lead Architect"},
        )
    )
    store.add_node(
        EntityNode(
            id="project:titan",
            name="Project Titan",
            entity_type="PROJECT",
            properties={"priority": "P0"},
        )
    )
    store.add_node(
        EntityNode(
            id="module:auth",
            name="Titan Auth Module",
            entity_type="MODULE",
            properties={"language": "Python"},
        )
    )

    # Populate relation edges
    store.add_edge(
        RelationEdge(
            id="edge:alice-leads-titan",
            source_id="person:alice",
            target_id="project:titan",
            relation_type="leads",
            weight=1.0,
        )
    )
    store.add_edge(
        RelationEdge(
            id="edge:titan-has-auth",
            source_id="project:titan",
            target_id="module:auth",
            relation_type="contains",
            weight=0.9,
        )
    )

    # Associate memories
    store.associate_memory(
        memory_id="mem_auth_spec",
        entity_id="module:auth",
        content="OAuth2 token validation guidelines designed by Alice.",
    )
    store.associate_memory(
        memory_id="mem_titan_plan",
        entity_id="project:titan",
        content="Project Titan roadmap for distributed authorization.",
    )

    return store


def test_create_graph_rrf_search_tool_metadata(
    populated_graph_store: SQLiteGraphMemoryStore,
) -> None:
    """Verify tool metadata conforms to LangChain BaseTool specifications."""
    retriever = DualChannelRRFRetriever(graph_store=populated_graph_store)
    tool = create_graph_rrf_search_tool(retriever)

    assert isinstance(tool, BaseTool)
    assert tool.name == "search_hybrid_knowledge_graph"
    assert "knowledge graph" in tool.description.lower()
    assert tool.args_schema is not None
    fields = tool.args_schema.model_fields
    assert "query" in fields
    assert "seed_entity_names" in fields
    assert "top_k" in fields


def test_agent_tool_invocation_with_graph_and_vector(
    populated_graph_store: SQLiteGraphMemoryStore,
) -> None:
    """Verify Agent runtime invocation of the search tool returning fused results."""
    # Mock vector channel callback
    def mock_vector_search(query: str, top_k: int) -> list[VectorHit]:
        return [
            VectorHit(
                memory_id="mem_auth_spec",
                content="OAuth2 token validation guidelines designed by Alice.",
                score=0.92,
                rank=1,
            ),
            VectorHit(
                memory_id="mem_irrelevant",
                content="Legacy database backup scripts.",
                score=0.45,
                rank=2,
            ),
        ]

    retriever = DualChannelRRFRetriever(
        graph_store=populated_graph_store,
        vector_search_fn=mock_vector_search,
    )
    tool = create_graph_rrf_search_tool(retriever)

    # Agent invokes tool with query and seed entity
    raw_result = tool.invoke(
        {
            "query": "Who is leading auth design?",
            "seed_entity_names": ["Alice"],
            "top_k": 3,
        }
    )
    assert isinstance(raw_result, str)
    data = json.loads(raw_result)

    assert data["query"] == "Who is leading auth design?"
    assert data["total_hits"] >= 1
    hits = data["fused_hits"]
    assert len(hits) >= 1

    top_hit = hits[0]
    assert top_hit["memory_id"] == "mem_auth_spec"
    assert "vector" in top_hit["hit_sources"]
    assert "graph" in top_hit["hit_sources"]
    assert top_hit["fused_score"] > 0
    assert top_hit["vector_rank"] == 1
    assert "vector_rrf" in top_hit["explanation"]


def test_memory_manager_hybrid_graph_rrf_runtime(
    populated_graph_store: SQLiteGraphMemoryStore,
) -> None:
    """Verify MemoryManager facade provides first-class graph-vector RRF search runtime."""
    manager = MemoryManager(
        user_id="test_user",
        config=MemoryConfig(
            embedding_model="text-embedding-3-small",
            security_scan_enabled=False,
        ),
    )

    # Runtime entity association
    manager.associate_memory_graph_entity(
        memory_id="mem_titan_qa",
        entity_id="project:titan",
        graph_store=populated_graph_store,
        content="QA testing strategy for Titan deployment.",
    )

    # Runtime hybrid search
    fused_results = manager.search_hybrid_graph_rrf(
        query="Titan deployment plan",
        graph_store=populated_graph_store,
        seed_entity_names=["Project Titan"],
        top_k=2,
    )

    assert len(fused_results) >= 1
    found_ids = [item.memory_id for item in fused_results]
    assert "mem_titan_qa" in found_ids or "mem_titan_plan" in found_ids
    assert fused_results[0].fused_score >= fused_results[-1].fused_score
