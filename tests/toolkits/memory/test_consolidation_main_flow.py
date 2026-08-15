"""Tests for consolidation main flow, helpers, and incremental-memory fetching.

Covers:
- _build_user_prompt: procedural trigger/action, source_error, plain content
- _build_id_map: short-id collision extension
- _execute_operations: MergeOp demote failure, UpdateContentOp locked rule
- get_last_consolidated_at / should_consolidate time gates
- _enrich_with_similar candidate search + error fallback
- _fetch_incremental_memories: vector scroll (consolidation-event skip, since filter),
  relational rules, truncation, per-store error tolerance
- _update_timestamp / _record_consolidation_event persistence guards
- run_consolidation: soft-lock, insufficient memories, LLM failure, no-ops, full success
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.memory.config import ConsolidationConfig
from myrm_agent_harness.toolkits.memory.strategies.consolidation import (
    ConsolidationResponse,
    ConsolidationStats,
    CorrectOp,
    MergeOp,
    UpdateContentOp,
    _build_id_map,
    _build_user_prompt,
    _enrich_with_similar,
    _execute_operations,
    _fetch_incremental_memories,
    _persist_insights,
    _record_consolidation_event,
    _update_timestamp,
    get_last_consolidated_at,
    run_consolidation,
    should_consolidate,
)
from myrm_agent_harness.toolkits.memory.types import (
    MemoryType,
    ProceduralMemory,
    SemanticMemory,
)
from myrm_agent_harness.toolkits.vector.base import VectorDocument


def _make_manager() -> AsyncMock:
    """Manager mock with async primitives and non-async backend accessors."""
    manager = AsyncMock()
    manager.user_id = "test-user"
    manager.namespaces = ["test-ns"]
    manager._namespaces = ["test-ns"]
    manager.has_vector = True
    manager.has_relational = True
    manager.config.semantic_collection = "test_semantic"
    manager.config.episodic_collection = "test_episodic"

    vector = AsyncMock()
    vector.scroll = AsyncMock(return_value=([], None))
    manager._vec = MagicMock(return_value=(vector, MagicMock()))
    manager._vec_store = vector

    relational = AsyncMock()
    relational.list_rules = AsyncMock(return_value=[])
    relational.set_profile = AsyncMock()
    manager._rel = MagicMock(return_value=relational)
    manager._rel_store = relational

    manager.get_profile_attribute = AsyncMock(return_value=None)
    manager.search = AsyncMock(return_value=[])
    manager.add_event = AsyncMock()
    manager.store = AsyncMock(return_value=MagicMock(id="stored-id"))
    manager.get_memory = AsyncMock(return_value=SemanticMemory(content="old content"))
    manager.update_memory = AsyncMock()
    manager.correct_memory = AsyncMock(return_value=MagicMock(id="corrected-id"))
    return manager


def _semantic_doc(mem_id: str, content: str, *, days_ago: int = 2) -> VectorDocument:
    return VectorDocument(
        id=mem_id,
        content=content,
        metadata={"user_id": "test-user", "importance": 0.8, "confidence": 0.9},
        created_at=datetime.now(UTC) - timedelta(days=days_ago),
    )


def _episodic_doc(
    mem_id: str, content: str, *, event_type: str = "conversation"
) -> VectorDocument:
    return VectorDocument(
        id=mem_id,
        content=content,
        metadata={"user_id": "test-user", "event_type": event_type},
        created_at=datetime.now(UTC) - timedelta(days=1),
    )


class TestBuildUserPrompt:
    def test_procedural_trigger_action_and_source_error(self) -> None:
        rule = ProceduralMemory(
            content="always check config", trigger="on start", action="read config"
        )
        mem = SemanticMemory(
            content="user prefers Rust", source_error="failed extraction attempt"
        )
        id_map = _build_id_map([rule, mem])
        prompt = _build_user_prompt([rule, mem], "2026-08-15", id_map)
        assert "  trigger: on start" in prompt
        assert "  action: read config" in prompt
        assert "  source_error: failed extraction attempt" in prompt
        assert "type=procedural" in prompt
        assert "type=semantic" in prompt
        assert "## Memories to analyze" in prompt

    def test_plain_content_line(self) -> None:
        mem = SemanticMemory(content="plain fact here")
        prompt = _build_user_prompt([mem], "2026-08-15", _build_id_map([mem]))
        assert "  plain fact here" in prompt
        assert prompt.endswith(
            "Analyze these memories and output a JSON object with operations and insights."
        )

    def test_new_tag_applied(self) -> None:
        mem = SemanticMemory(content="fresh fact")
        id_map = _build_id_map([mem])
        prompt = _build_user_prompt(
            [mem], "2026-08-15", id_map, new_ids=frozenset({mem.id})
        )
        assert " [NEW]" in prompt

    def test_memory_without_importance_confidence(self) -> None:
        minimal = SimpleNamespace(
            id="minimal-1",
            content="bare memory",
            created_at=datetime.now(UTC),
            memory_type=MemoryType.PROCEDURAL,
        )
        prompt = _build_user_prompt([minimal], "2026-08-15", _build_id_map([minimal]))
        assert "type=procedural" in prompt
        assert "importance" not in prompt
        assert "confidence" not in prompt

    def test_correction_of_emits_corrects_marker(self) -> None:
        original = SemanticMemory(content="original fact", id="orig-12345678")
        correction = SemanticMemory(
            content="corrected fact", id="corr-12345678", correction_of=original.id
        )
        id_map = _build_id_map([original, correction])
        prompt = _build_user_prompt([original, correction], "2026-08-15", id_map)
        assert "corrects:orig-123" in prompt


class TestPersistInsights:
    @pytest.mark.asyncio
    async def test_no_vector_skips(self) -> None:
        manager = _make_manager()
        manager.has_vector = False
        await _persist_insights(manager, ["an insight"])
        manager.store.assert_not_called()

    @pytest.mark.asyncio
    async def test_short_insight_skipped(self) -> None:
        manager = _make_manager()
        manager.store = AsyncMock()
        await _persist_insights(manager, ["too short"])
        manager.store.assert_not_called()

    @pytest.mark.asyncio
    async def test_store_error_is_tolerated(self) -> None:
        manager = _make_manager()
        manager.store = AsyncMock(side_effect=RuntimeError("store down"))
        await _persist_insights(manager, ["this is a sufficiently long insight"])
        manager.store.assert_awaited_once()


class TestBuildIdMap:
    def test_short_id_collision_extends(self) -> None:
        # First 8 chars identical -> second id must be extended to avoid collision.
        mem_a = SimpleNamespace(
            id="abcdefgh1111",
            content="a",
            created_at=datetime.now(UTC),
            memory_type=MemoryType.SEMANTIC,
        )
        mem_b = SimpleNamespace(
            id="abcdefgh2222",
            content="b",
            created_at=datetime.now(UTC),
            memory_type=MemoryType.SEMANTIC,
        )
        id_map = _build_id_map([mem_a, mem_b])
        assert id_map["abcdefgh"] == "abcdefgh1111"
        assert id_map["abcdefgh2222"] == "abcdefgh2222"
        assert len(id_map) == 2


class TestExecuteOperationsExtraBranches:
    @pytest.mark.asyncio
    async def test_merge_demote_failure_is_tolerated(self) -> None:
        """A failing demote must not abort the merge or bump errors."""
        manager = _make_manager()
        manager.update_memory = AsyncMock(side_effect=RuntimeError("demote failed"))
        id_map = {"m1": "m1", "m2": "m2"}
        ops = [
            MergeOp(source_ids=["m1", "m2"], merged_content="merged", importance=0.8)
        ]
        stats = await _execute_operations(ops, manager, id_map)
        assert stats.merged == 1
        assert stats.errors == 0

    @pytest.mark.asyncio
    async def test_update_content_locked_rule_skipped(self) -> None:
        locked = ProceduralMemory(
            content="locked", trigger="t", action="a", is_user_locked=True
        )
        manager = _make_manager()
        manager.get_memory = AsyncMock(return_value=locked)
        ops = [UpdateContentOp(memory_id="mem-1", new_content="new", importance=0.3)]
        stats = await _execute_operations(ops, manager)
        assert stats.updated == 0
        manager.update_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_content_applies(self) -> None:
        manager = _make_manager()
        manager.get_memory = AsyncMock(return_value=SemanticMemory(content="old"))
        ops = [UpdateContentOp(memory_id="mem-1", new_content="new", importance=0.3)]
        stats = await _execute_operations(ops, manager)
        manager.update_memory.assert_awaited_once()
        assert stats.updated == 1


class TestLastConsolidatedAt:
    @pytest.mark.asyncio
    async def test_no_relational_returns_none(self) -> None:
        manager = _make_manager()
        manager.has_relational = False
        assert await get_last_consolidated_at(manager) is None

    @pytest.mark.asyncio
    async def test_no_raw_value_returns_none(self) -> None:
        manager = _make_manager()
        manager.get_profile_attribute = AsyncMock(return_value=None)
        assert await get_last_consolidated_at(manager) is None

    @pytest.mark.asyncio
    async def test_invalid_raw_value_returns_none(self) -> None:
        manager = _make_manager()
        manager.get_profile_attribute = AsyncMock(return_value="not-a-date")
        assert await get_last_consolidated_at(manager) is None

    @pytest.mark.asyncio
    async def test_valid_raw_value_parsed(self) -> None:
        manager = _make_manager()
        ts = datetime.now(UTC)
        manager.get_profile_attribute = AsyncMock(return_value=ts.isoformat())
        parsed = await get_last_consolidated_at(manager)
        assert parsed is not None
        assert abs((parsed - ts).total_seconds()) < 1


class TestShouldConsolidate:
    @pytest.mark.asyncio
    async def test_disabled_returns_false(self) -> None:
        config = ConsolidationConfig(enabled=False)
        assert await should_consolidate(_make_manager(), config) is False

    @pytest.mark.asyncio
    async def test_no_last_consolidation_returns_true(self) -> None:
        config = ConsolidationConfig()
        manager = _make_manager()
        manager.get_profile_attribute = AsyncMock(return_value=None)
        assert await should_consolidate(manager, config) is True

    @pytest.mark.asyncio
    async def test_elapsed_below_interval_returns_false(self) -> None:
        config = ConsolidationConfig(interval_hours=24)
        manager = _make_manager()
        manager.get_profile_attribute = AsyncMock(
            return_value=datetime.now(UTC).isoformat()
        )
        assert await should_consolidate(manager, config) is False

    @pytest.mark.asyncio
    async def test_elapsed_above_interval_returns_true(self) -> None:
        config = ConsolidationConfig(interval_hours=24)
        manager = _make_manager()
        manager.get_profile_attribute = AsyncMock(
            return_value=(datetime.now(UTC) - timedelta(hours=25)).isoformat()
        )
        assert await should_consolidate(manager, config) is True


class TestEnrichWithSimilar:
    def _search_result(self, memory: SemanticMemory) -> SimpleNamespace:
        return SimpleNamespace(memory=memory)

    @pytest.mark.asyncio
    async def test_no_candidates_returns_alone(self) -> None:
        manager = _make_manager()
        manager.search = AsyncMock(return_value=[])
        base = SemanticMemory(content="base")
        result = await _enrich_with_similar(base, manager)
        assert result == [base]

    @pytest.mark.asyncio
    async def test_candidates_filter_self_and_truncate(self) -> None:
        manager = _make_manager()
        base = SemanticMemory(content="base")
        same = SemanticMemory(content="base", id=base.id)
        other = SemanticMemory(content="other")
        manager.search = AsyncMock(
            return_value=[self._search_result(same), self._search_result(other)]
        )
        result = await _enrich_with_similar(base, manager, max_similar=1)
        assert result == [base, other]

    @pytest.mark.asyncio
    async def test_search_error_returns_alone(self) -> None:
        manager = _make_manager()
        manager.search = AsyncMock(side_effect=RuntimeError("search down"))
        base = SemanticMemory(content="base")
        assert await _enrich_with_similar(base, manager) == [base]


class TestFetchIncrementalMemories:
    @pytest.mark.asyncio
    async def test_vector_and_relational_combined_truncated(self) -> None:
        manager = _make_manager()
        vector = manager._vec_store
        vector.scroll = AsyncMock(
            side_effect=[
                (
                    [
                        _semantic_doc("s-1", "semantic fact"),
                        _semantic_doc("s-2", "semantic fact 2"),
                    ],
                    None,
                ),
                ([_episodic_doc("e-1", "event fact")], None),
            ]
        )
        manager._rel_store.list_rules = AsyncMock(
            return_value=[
                ProceduralMemory(
                    content="rule",
                    trigger="t",
                    action="a",
                    created_at=datetime.now(UTC) - timedelta(hours=1),
                )
            ]
        )
        result = await _fetch_incremental_memories(
            manager, since=datetime.now(UTC) - timedelta(days=3), max_count=2
        )
        assert len(result) == 2
        assert all(hasattr(m, "created_at") for m in result)

    @pytest.mark.asyncio
    async def test_since_filter_and_consolidation_event_skipped(self) -> None:
        manager = _make_manager()
        vector = manager._vec_store
        vector.scroll = AsyncMock(
            side_effect=[
                ([_semantic_doc("old", "too old", days_ago=10)], None),
                ([_episodic_doc("consol", "event", event_type="consolidation")], None),
            ]
        )
        result = await _fetch_incremental_memories(
            manager, since=datetime.now(UTC) - timedelta(days=2), max_count=5
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_vector_scroll_error_is_tolerated(self) -> None:
        manager = _make_manager()
        vector = manager._vec_store
        vector.scroll = AsyncMock(side_effect=RuntimeError("vector down"))
        result = await _fetch_incremental_memories(manager, since=None, max_count=5)
        assert result == []

    @pytest.mark.asyncio
    async def test_no_vector_uses_relational_only(self) -> None:
        manager = _make_manager()
        manager.has_vector = False
        manager._rel_store.list_rules = AsyncMock(
            return_value=[ProceduralMemory(content="rule", trigger="t", action="a")]
        )
        result = await _fetch_incremental_memories(manager, since=None, max_count=5)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_relational_error_is_tolerated(self) -> None:
        manager = _make_manager()
        vector = manager._vec_store
        vector.scroll = AsyncMock(
            side_effect=[([_semantic_doc("s-1", "fact")], None), ([], None)]
        )
        manager._rel_store.list_rules = AsyncMock(side_effect=RuntimeError("rel down"))
        result = await _fetch_incremental_memories(manager, since=None, max_count=5)
        assert len(result) == 1


class TestUpdateTimestamp:
    @pytest.mark.asyncio
    async def test_no_relational_skips(self) -> None:
        manager = _make_manager()
        manager.has_relational = False
        await _update_timestamp(manager, datetime.now(UTC))
        manager._rel_store.set_profile.assert_not_called()

    @pytest.mark.asyncio
    async def test_persists_isoformat(self) -> None:
        manager = _make_manager()
        ts = datetime.now(UTC)
        await _update_timestamp(manager, ts)
        manager._rel_store.set_profile.assert_awaited_once()
        stored = manager._rel_store.set_profile.call_args[0][1]
        assert datetime.fromisoformat(stored) is not None

    @pytest.mark.asyncio
    async def test_persist_error_is_tolerated(self) -> None:
        manager = _make_manager()
        manager._rel_store.set_profile = AsyncMock(
            side_effect=RuntimeError("write failed")
        )
        await _update_timestamp(manager, datetime.now(UTC))  # must not raise


class TestRecordConsolidationEvent:
    @pytest.mark.asyncio
    async def test_no_vector_skips(self) -> None:
        manager = _make_manager()
        manager.has_vector = False
        await _record_consolidation_event(manager, ConsolidationStats())
        manager.add_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_summary_includes_affected_ids(self) -> None:
        manager = _make_manager()
        stats = ConsolidationStats(
            merged=1, affected_ids=["a-1", "a-2"], input_count=3, duration_ms=12.5
        )
        await _record_consolidation_event(manager, stats)
        manager.add_event.assert_awaited_once()
        kwargs = manager.add_event.call_args.kwargs
        assert kwargs["event_type"] == "consolidation"
        assert "[affected_ids:a-1,a-2]" in kwargs["content"]
        assert "input 3" in kwargs["content"]

    @pytest.mark.asyncio
    async def test_add_event_error_is_tolerated(self) -> None:
        manager = _make_manager()
        manager.add_event = AsyncMock(side_effect=RuntimeError("event store down"))
        await _record_consolidation_event(
            manager, ConsolidationStats()
        )  # must not raise


def _make_llm(response: ConsolidationResponse) -> MagicMock:
    structured = AsyncMock()
    structured.ainvoke = AsyncMock(return_value=response)
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


class TestRunConsolidation:
    @pytest.mark.asyncio
    async def test_soft_lock_skips(self) -> None:
        manager = _make_manager()
        manager.get_profile_attribute = AsyncMock(
            return_value=(datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        )
        config = ConsolidationConfig(soft_lock_hours=1.0)
        stats = await run_consolidation(
            manager, _make_llm(ConsolidationResponse()), config
        )
        assert stats.total_processed == 0
        manager._vec_store.scroll.assert_not_called()

    @pytest.mark.asyncio
    async def test_insufficient_memories_skips(self) -> None:
        manager = _make_manager()
        manager._vec_store.scroll = AsyncMock(
            side_effect=[([_semantic_doc("s-1", "solo")], None), ([], None)]
        )
        stats = await run_consolidation(
            manager, _make_llm(ConsolidationResponse()), ConsolidationConfig()
        )
        assert stats.total_processed == 0
        manager._rel_store.set_profile.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_llm_failure_returns_error_stats(self) -> None:
        manager = _make_manager()
        manager._vec_store.scroll = AsyncMock(
            side_effect=[
                ([_semantic_doc("s-1", "a"), _semantic_doc("s-2", "b")], None),
                ([], None),
            ]
        )
        structured = AsyncMock()
        structured.ainvoke = AsyncMock(side_effect=RuntimeError("llm down"))
        llm = MagicMock()
        llm.with_structured_output.return_value = structured
        stats = await run_consolidation(manager, llm, ConsolidationConfig())
        assert stats.errors == 1
        assert stats.input_count == 2

    @pytest.mark.asyncio
    async def test_no_operations_returns_empty(self) -> None:
        manager = _make_manager()
        manager._vec_store.scroll = AsyncMock(
            side_effect=[
                ([_semantic_doc("s-1", "a"), _semantic_doc("s-2", "b")], None),
                ([], None),
            ]
        )
        stats = await run_consolidation(
            manager,
            _make_llm(ConsolidationResponse(operations=[], insights=[])),
            ConsolidationConfig(),
        )
        assert stats.merged == 0
        assert stats.insights == ()

    @pytest.mark.asyncio
    async def test_full_success_with_rubric_filter_insights_and_complete(self) -> None:
        manager = _make_manager()
        manager._vec_store.scroll = AsyncMock(
            side_effect=[
                ([_semantic_doc("s-1", "a"), _semantic_doc("s-2", "b")], None),
                ([], None),
            ]
        )
        response = ConsolidationResponse(
            operations=[
                MergeOp(
                    source_ids=["s-1", "s-2"],
                    merged_content="merged",
                    accuracy_score=0.9,
                    importance=0.8,
                ),
                CorrectOp(
                    memory_id="s-1",
                    corrected_content="corrected",
                    accuracy_score=0.2,
                    importance=0.2,
                ),
            ],
            insights=["cross-cutting insight"],
        )
        on_complete = AsyncMock()
        stats = await run_consolidation(
            manager, _make_llm(response), ConsolidationConfig(), on_complete=on_complete
        )
        assert stats.merged == 1
        assert stats.corrected == 0  # low-scoring op filtered out by rubric
        assert stats.insights == ("cross-cutting insight",)
        assert stats.input_count == 2
        manager.add_event.assert_awaited()
        manager._rel_store.set_profile.assert_awaited()
        on_complete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_complete_hook_error_is_non_fatal(self) -> None:
        manager = _make_manager()
        manager._vec_store.scroll = AsyncMock(
            side_effect=[
                ([_semantic_doc("s-1", "a"), _semantic_doc("s-2", "b")], None),
                ([], None),
            ]
        )
        response = ConsolidationResponse(operations=[], insights=["only insight"])
        on_complete = AsyncMock(side_effect=RuntimeError("hook failed"))
        stats = await run_consolidation(
            manager, _make_llm(response), ConsolidationConfig(), on_complete=on_complete
        )
        assert stats.insights == ("only insight",)
        on_complete.assert_awaited_once()
