from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.memory._internal.maintenance import run_forgetting
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument
from myrm_agent_harness.toolkits.memory.strategies.forgetting import ForgettingConfig, ForgettingMode
from myrm_agent_harness.toolkits.memory.types import SemanticMemory


@pytest.mark.asyncio
async def test_run_forgetting_delete_mode():
    fg_cfg = ForgettingConfig(mode=ForgettingMode.DELETE, max_forget_per_run=10)
    config = MemoryConfig(embedding_model="test", forgetting=fg_cfg)

    vector = AsyncMock()
    graph = AsyncMock()

    # Mock scroll to return some documents
    doc1 = VectorDocument(id="doc1", content="test", metadata={"importance": 0.1}, embedding=[0.1])
    vector.scroll.side_effect = [([doc1], None), ([], None)]

    vector.delete.return_value = 1

    with patch("myrm_agent_harness.toolkits.memory.strategies.forgetting.ForgettingStrategy.select_candidates") as mock_select:
        mock_select.return_value = [(SemanticMemory(id="doc1", content="test", metadata={}), MagicMock(total_score=0.1))]
        result = await run_forgetting(vector, config, graph)

    assert result.forgotten_count == 2
    assert "doc1" in result.forgotten_ids
    graph.delete_subgraph.assert_called_with("doc1")

@pytest.mark.asyncio
async def test_run_forgetting_archive_mode():
    fg_cfg = ForgettingConfig(mode=ForgettingMode.ARCHIVE, max_forget_per_run=10)
    config = MemoryConfig(embedding_model="test", forgetting=fg_cfg)

    vector = AsyncMock()

    # Mock scroll to return some documents
    doc1 = VectorDocument(id="doc1", content="test", metadata={"importance": 0.1}, embedding=[0.1])
    vector.scroll.side_effect = [([doc1], None), ([], None)]

    with patch("myrm_agent_harness.toolkits.memory.strategies.forgetting.ForgettingStrategy.select_candidates") as mock_select:
        mock_select.return_value = [(SemanticMemory(id="doc1", content="test", metadata={}), MagicMock(total_score=0.1))]
        result = await run_forgetting(vector, config)

    assert result.archived_count == 1
    assert "doc1" in result.archived_ids
    vector.upsert.assert_called_once()
    upserted_docs = vector.upsert.call_args[0][1]
    assert upserted_docs[0].metadata["status"] == "archived"

@pytest.mark.asyncio
async def test_run_forgetting_delete_graph_error():
    fg_cfg = ForgettingConfig(mode=ForgettingMode.DELETE, max_forget_per_run=10)
    config = MemoryConfig(embedding_model="test", forgetting=fg_cfg)

    vector = AsyncMock()
    graph = AsyncMock()

    doc1 = VectorDocument(id="doc1", content="test", metadata={"importance": 0.1}, embedding=[0.1])
    vector.scroll.side_effect = [([doc1], None), ([], None)]

    vector.delete.return_value = 1
    graph.delete_subgraph.side_effect = Exception("Graph error")

    with patch("myrm_agent_harness.toolkits.memory.strategies.forgetting.ForgettingStrategy.select_candidates") as mock_select:
        mock_select.return_value = [(SemanticMemory(id="doc1", content="test", metadata={}), MagicMock(total_score=0.1))]
        result = await run_forgetting(vector, config, graph)

    assert result.forgotten_count == 2
    assert len(result.errors) == 2
    assert result.errors[0][0] == "doc1"
