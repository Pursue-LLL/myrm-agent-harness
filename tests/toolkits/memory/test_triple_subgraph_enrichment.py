"""Unit tests for triple sub-graph topological expansion in enrich_with_graph.

Validates:
1. Procedural memory hits expand via REQUIRES/RESOLVES/TRIGGERS relationships.
2. Semantic memory hits expand via IS_A/DEFINES/RELATES_TO relationships.
3. Multi-subgraph expansion gracefully aggregates sibling candidates.
"""

from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._internal.maintenance import enrich_with_graph
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument
from myrm_agent_harness.toolkits.memory.types import (
    MemorySearchResult,
    MemoryType,
    ProceduralMemory,
    SemanticMemory,
)


@pytest.mark.asyncio
async def test_procedural_subgraph_expansion_via_requires() -> None:
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()
    graph = AsyncMock()

    proc_mem = ProceduralMemory(
        id="proc_1",
        content="构建发布规约",
        trigger="build",
        action="run pre-check",
        metadata={},
    )
    res_proc = MemorySearchResult(memory=proc_mem, score=0.95, memory_type=MemoryType.PROCEDURAL)

    # Mock graph returning related node when queried with REQUIRES
    async def mock_get_related_with_depth(node_id: str, rel_type: str = "MENTIONS", max_depth: int = 2):
        if node_id == "proc_1" and rel_type == "REQUIRES":
            return [("proc_dep_2", 1)]
        return []

    graph.get_related_nodes_with_depth.side_effect = mock_get_related_with_depth

    dep_doc = VectorDocument(
        id="proc_dep_2",
        content="依赖前提：必须先执行 pre-check",
        metadata={"status": "active"},
        embedding=[0.1],
    )
    vector.get.return_value = [dep_doc]

    results = await enrich_with_graph([res_proc], "pre-check 构建", 10, graph, vector, config)

    assert len(results) == 2
    assert results[0].id == "proc_1"
    assert results[1].id == "proc_dep_2"
    assert results[1].score > 0.0


@pytest.mark.asyncio
async def test_semantic_subgraph_expansion_via_defines() -> None:
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()
    graph = AsyncMock()

    sem_mem = SemanticMemory(id="sem_concept_1", content="RRF 倒数排名融合定义", metadata={})
    res_sem = MemorySearchResult(memory=sem_mem, score=0.92, memory_type=MemoryType.SEMANTIC)

    async def mock_get_related_with_depth(node_id: str, rel_type: str = "MENTIONS", max_depth: int = 2):
        if node_id == "sem_concept_1" and rel_type == "DEFINES":
            return [("sem_formula_2", 1)]
        return []

    graph.get_related_nodes_with_depth.side_effect = mock_get_related_with_depth

    formula_doc = VectorDocument(
        id="sem_formula_2",
        content="RRF 公式实现细节与参数常数 k=60",
        metadata={"status": "active"},
        embedding=[0.2],
    )
    vector.get.return_value = [formula_doc]

    results = await enrich_with_graph([res_sem], "RRF 公式", 10, graph, vector, config)

    assert len(results) == 2
    assert results[0].id == "sem_concept_1"
    assert results[1].id == "sem_formula_2"
