from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.memory._internal.maintenance import run_forgetting
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument
from myrm_agent_harness.toolkits.memory.strategies.forgetting import (
    ForgettingConfig,
    ForgettingMode,
    ForgettingStrategy,
)
from myrm_agent_harness.toolkits.memory.types import (
    ProceduralMemory,
    SemanticMemory,
    ToolRulePriority,
)


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
    assert upserted_docs[0].metadata["archived"] is True

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


def test_forgetting_scores_procedural_memory_without_vector_importance() -> None:
    rule = ProceduralMemory(content="rule", trigger="when", action="do")
    score = ForgettingStrategy().calculate_retention_score(rule)
    assert score.importance_score == 0.5


def test_ttl_expired_filters_by_expected_valid_days() -> None:
    from myrm_agent_harness.toolkits.memory.strategies.forgetting import ttl_expired

    now = datetime.now(UTC)
    expired = ProceduralMemory(
        id="expired",
        content="old",
        trigger="when",
        action="do",
        expected_valid_days=1,
        created_at=now - timedelta(days=2),
    )
    boundary = ProceduralMemory(
        id="boundary",
        content="boundary",
        trigger="when",
        action="do",
        expected_valid_days=1,
        created_at=now - timedelta(days=1),
    )
    fresh = ProceduralMemory(
        id="fresh",
        content="new",
        trigger="when",
        action="do",
        expected_valid_days=1,
        created_at=now - timedelta(hours=1),
    )
    no_evd = ProceduralMemory(
        id="no-evd", content="no ttl", trigger="when", action="do"
    )

    result = ttl_expired([expired, boundary, fresh, no_evd], now=now)

    assert {r.id for r in result} == {"expired", "boundary"}


@pytest.mark.asyncio
async def test_run_forgetting_handles_procedural_rules_without_importance_attribute() -> None:
    config = MemoryConfig(
        embedding_model="test",
        forgetting=ForgettingConfig(mode=ForgettingMode.ARCHIVE, max_forget_per_run=10),
    )
    vector = AsyncMock()
    vector.scroll.side_effect = [([], None), ([], None)]
    relational = AsyncMock()
    rule = ProceduralMemory(
        id="rule-1",
        content="old rule",
        trigger="when",
        action="do",
        created_at=datetime.now(UTC) - timedelta(days=1000),
        user_rating=0.0,
    )
    relational.list_rules.return_value = [rule]

    result = await run_forgetting(vector, config, relational=relational)

    assert result.archived_count == 1
    relational.update_rule.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_forgetting_archives_ttl_expired_rules() -> None:
    """Rules past expected_valid_days are archived regardless of retention score."""
    config = MemoryConfig(
        embedding_model="test",
        forgetting=ForgettingConfig(mode=ForgettingMode.ARCHIVE, max_forget_per_run=10),
    )
    vector = AsyncMock()
    vector.scroll.side_effect = [([], None), ([], None)]
    relational = AsyncMock()
    expired = ProceduralMemory(
        id="ttl-expired",
        content="transient tool failure",
        trigger="web_fetch_tool repeated failure",
        action="consider alternative",
        expected_valid_days=1,
        created_at=datetime.now(UTC) - timedelta(days=2),
    )
    fresh = ProceduralMemory(
        id="ttl-fresh",
        content="new failure",
        trigger="bash repeated failure",
        action="consider alternative",
        expected_valid_days=1,
        created_at=datetime.now(UTC) - timedelta(hours=1),
    )
    relational.list_rules.return_value = [expired, fresh]

    result = await run_forgetting(vector, config, relational=relational)

    assert result.archived_count == 1
    assert "ttl-expired" in result.archived_ids
    relational.update_rule.assert_awaited_once()
    archived_call = relational.update_rule.await_args
    assert archived_call is not None
    updated_rule = archived_call.args[1]
    assert updated_rule.id == "ttl-expired"
    assert updated_rule.metadata.get("archive_reason", "").startswith("ttl_expired")


@pytest.mark.asyncio
async def test_run_forgetting_ttl_expired_not_sent_through_retention() -> None:
    """TTL-expired rules are excluded from retention scoring."""
    config = MemoryConfig(
        embedding_model="test",
        forgetting=ForgettingConfig(mode=ForgettingMode.ARCHIVE, max_forget_per_run=10),
    )
    vector = AsyncMock()
    vector.scroll.side_effect = [([], None), ([], None)]
    relational = AsyncMock()
    expired = ProceduralMemory(
        id="ttl-expired",
        content="transient tool failure",
        trigger="repeated failure",
        action="consider alternative",
        expected_valid_days=1,
        created_at=datetime.now(UTC) - timedelta(days=3),
    )
    relational.list_rules.return_value = [expired]

    with patch(
        "myrm_agent_harness.toolkits.memory.strategies.forgetting.ForgettingStrategy.select_candidates"
    ) as mock_select:
        mock_select.return_value = []
        result = await run_forgetting(vector, config, relational=relational)

    assert result.archived_count == 1
    # All calls receive empty lists: the TTL-expired rule never reaches retention scoring.
    mock_select.assert_called_with([], {})


@pytest.mark.asyncio
async def test_run_forgetting_ttl_skips_critical_rules() -> None:
    """CRITICAL rules with expired expected_valid_days are never TTL-archived.

    User-mandated behavior encoded as CRITICAL priority flows through retention
    scoring (importance floor) instead of being archived on TTL expiry.
    """
    config = MemoryConfig(
        embedding_model="test",
        forgetting=ForgettingConfig(mode=ForgettingMode.ARCHIVE, max_forget_per_run=10),
    )
    vector = AsyncMock()
    vector.scroll.side_effect = [([], None), ([], None)]
    relational = AsyncMock()
    critical_expired = ProceduralMemory(
        id="critical-expired",
        content="user mandate",
        trigger="deploy",
        action="always dry-run first",
        tool_rule_priority=ToolRulePriority.CRITICAL,
        expected_valid_days=1,
        created_at=datetime.now(UTC) - timedelta(days=5),
    )
    relational.list_rules.return_value = [critical_expired]

    with patch(
        "myrm_agent_harness.toolkits.memory.strategies.forgetting.ForgettingStrategy.select_candidates"
    ) as mock_select:
        mock_select.return_value = []
        result = await run_forgetting(vector, config, relational=relational)

    assert result.archived_count == 0
    assert result.forgotten_count == 0
    relational.update_rule.assert_not_awaited()
