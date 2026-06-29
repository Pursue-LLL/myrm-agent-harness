"""Tests for consolidation rollback functionality.

Covers:
- _parse_affected_ids regex extraction
- ConsolidationRollbackResult model
- get_last_consolidation_summary: no events, with events, conflict detection
- rollback_last_consolidation: MergeOp, CorrectOp, UpdateContentOp rollback paths
- affected_ids collection in _execute_operations
- Edge cases: deleted memories, empty affected_ids
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.memory.strategies.consolidation_rollback import (
    ConsolidationRollbackResult,
    _parse_affected_ids,
    get_last_consolidation_summary,
    rollback_last_consolidation,
)


class TestParseAffectedIds:
    def test_empty_content(self) -> None:
        assert _parse_affected_ids("") == []

    def test_no_marker(self) -> None:
        assert _parse_affected_ids("Memory consolidation: input 5, enriched 3") == []

    def test_single_id(self) -> None:
        content = "consolidation stats\n[affected_ids:mem-1]"
        assert _parse_affected_ids(content) == ["mem-1"]

    def test_multiple_ids(self) -> None:
        content = "stats\n[affected_ids:mem-1,mem-2,mem-3]"
        assert _parse_affected_ids(content) == ["mem-1", "mem-2", "mem-3"]

    def test_ids_with_spaces(self) -> None:
        content = "[affected_ids: mem-1 , mem-2 ]"
        assert _parse_affected_ids(content) == ["mem-1", "mem-2"]

    def test_empty_ids_string(self) -> None:
        content = "[affected_ids:]"
        assert _parse_affected_ids(content) == []

    def test_ids_with_trailing_comma(self) -> None:
        content = "[affected_ids:mem-1,mem-2,]"
        result = _parse_affected_ids(content)
        assert result == ["mem-1", "mem-2"]


class TestConsolidationRollbackResult:
    def test_defaults(self) -> None:
        result = ConsolidationRollbackResult()
        assert result.rolled_back == 0
        assert result.skipped_conflict == 0
        assert result.errors == 0
        assert result.conflict_ids == []

    def test_with_values(self) -> None:
        result = ConsolidationRollbackResult(
            rolled_back=3, skipped_conflict=1, errors=0, conflict_ids=["id-x"]
        )
        assert result.rolled_back == 3
        assert result.conflict_ids == ["id-x"]


class TestGetLastConsolidationSummary:
    @pytest.mark.asyncio
    async def test_no_events(self) -> None:
        manager = AsyncMock()
        manager.list_memories = AsyncMock(return_value=[])
        result = await get_last_consolidation_summary(manager)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_consolidation_events(self) -> None:
        from myrm_agent_harness.toolkits.memory.types import EpisodicMemory

        non_consolidation = EpisodicMemory(
            content="session ended",
            event_type="session_end",
            user_id="test",
        )
        manager = AsyncMock()
        manager.list_memories = AsyncMock(return_value=[non_consolidation])
        result = await get_last_consolidation_summary(manager)
        assert result is None

    @pytest.mark.asyncio
    async def test_with_consolidation_event_no_conflicts(self) -> None:
        from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, SemanticMemory

        now = datetime.now(UTC)
        event = EpisodicMemory(
            content="Memory consolidation: input 5, enriched 3\n[affected_ids:mem-1,mem-2]",
            event_type="consolidation",
            user_id="test",
        )
        object.__setattr__(event, "created_at", now)

        mem1 = SemanticMemory(content="c1", user_id="test", importance=0.7)
        object.__setattr__(mem1, "updated_at", now - timedelta(seconds=10))

        mem2 = SemanticMemory(content="c2", user_id="test", importance=0.7)
        object.__setattr__(mem2, "updated_at", now - timedelta(seconds=10))

        manager = AsyncMock()
        manager.list_memories = AsyncMock(return_value=[event])
        manager.get_memory = AsyncMock(side_effect=lambda aid: mem1 if aid == "mem-1" else mem2)

        result = await get_last_consolidation_summary(manager)
        assert result is not None
        assert result["rollback_available"] is True
        assert result["affected_count"] == 2
        assert result["conflict_ids"] == []

    @pytest.mark.asyncio
    async def test_with_conflict_detected(self) -> None:
        from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, SemanticMemory

        now = datetime.now(UTC)
        event = EpisodicMemory(
            content="consolidation\n[affected_ids:mem-1]",
            event_type="consolidation",
            user_id="test",
        )
        object.__setattr__(event, "created_at", now - timedelta(minutes=5))

        mem1 = SemanticMemory(content="modified", user_id="test", importance=0.7)
        object.__setattr__(mem1, "updated_at", now)

        manager = AsyncMock()
        manager.list_memories = AsyncMock(return_value=[event])
        manager.get_memory = AsyncMock(return_value=mem1)

        result = await get_last_consolidation_summary(manager)
        assert result is not None
        assert result["rollback_available"] is False
        assert "mem-1" in result["conflict_ids"]


class TestRollbackLastConsolidation:
    @pytest.mark.asyncio
    async def test_no_events(self) -> None:
        manager = AsyncMock()
        manager.list_memories = AsyncMock(return_value=[])
        result = await rollback_last_consolidation(manager)
        assert result.rolled_back == 0

    @pytest.mark.asyncio
    async def test_rollback_merge_op(self) -> None:
        from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, SemanticMemory

        now = datetime.now(UTC)
        event = EpisodicMemory(
            content="consolidation\n[affected_ids:merged-new,source-1,source-2]",
            event_type="consolidation",
            user_id="test",
        )
        object.__setattr__(event, "created_at", now)

        merged_mem = SemanticMemory(
            content="merged content",
            user_id="test",
            importance=0.9,
            metadata={"consolidation_source": "source-1,source-2"},
        )
        object.__setattr__(merged_mem, "id", "merged-new")
        object.__setattr__(merged_mem, "updated_at", now - timedelta(seconds=1))

        source1 = SemanticMemory(
            content="old content 1",
            user_id="test",
            importance=0.05,
            metadata={"consolidated": True},
        )
        object.__setattr__(source1, "updated_at", now - timedelta(seconds=1))

        source2 = SemanticMemory(
            content="old content 2",
            user_id="test",
            importance=0.05,
            metadata={"consolidated": True},
        )
        object.__setattr__(source2, "updated_at", now - timedelta(seconds=1))

        def get_mem(aid: str):
            if aid == "merged-new":
                return merged_mem
            if aid == "source-1":
                return source1
            return source2

        manager = AsyncMock()
        manager.list_memories = AsyncMock(return_value=[event])
        manager.get_memory = AsyncMock(side_effect=get_mem)
        manager.delete_memory = AsyncMock()
        manager.update_memory = AsyncMock()
        manager.config = MagicMock()
        manager.config.semantic_collection = "test_semantic"

        result = await rollback_last_consolidation(manager)
        assert result.rolled_back == 3
        manager.delete_memory.assert_called_once_with("test_semantic", ["merged-new"])
        assert manager.update_memory.call_count == 2

    @pytest.mark.asyncio
    async def test_rollback_correct_op(self) -> None:
        from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, SemanticMemory

        now = datetime.now(UTC)
        event = EpisodicMemory(
            content="consolidation\n[affected_ids:original-1,correction-1]",
            event_type="consolidation",
            user_id="test",
        )
        object.__setattr__(event, "created_at", now)

        original = SemanticMemory(
            content="wrong content",
            user_id="test",
            importance=0.05,
            confidence=0.1,
            metadata={"corrected": True},
        )
        object.__setattr__(original, "updated_at", now - timedelta(seconds=1))

        correction = SemanticMemory(
            content="corrected content",
            user_id="test",
            importance=0.9,
            correction_of="original-1",
        )
        object.__setattr__(correction, "id", "correction-1")
        object.__setattr__(correction, "updated_at", now - timedelta(seconds=1))

        def get_mem(aid: str):
            return original if aid == "original-1" else correction

        manager = AsyncMock()
        manager.list_memories = AsyncMock(return_value=[event])
        manager.get_memory = AsyncMock(side_effect=get_mem)
        manager.delete_memory = AsyncMock()
        manager.update_memory = AsyncMock()
        manager.config = MagicMock()
        manager.config.semantic_collection = "test_semantic"

        result = await rollback_last_consolidation(manager)
        assert result.rolled_back == 2
        manager.delete_memory.assert_called_once_with("test_semantic", ["correction-1"])
        manager.update_memory.assert_called_once()

    @pytest.mark.asyncio
    async def test_rollback_update_content_op(self) -> None:
        from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, SemanticMemory

        now = datetime.now(UTC)
        event = EpisodicMemory(
            content="consolidation\n[affected_ids:mem-1]",
            event_type="consolidation",
            user_id="test",
        )
        object.__setattr__(event, "created_at", now)

        mem = SemanticMemory(
            content="updated content",
            user_id="test",
            importance=0.8,
            metadata={"previous_content": "original content"},
        )
        object.__setattr__(mem, "updated_at", now - timedelta(seconds=1))

        manager = AsyncMock()
        manager.list_memories = AsyncMock(return_value=[event])
        manager.get_memory = AsyncMock(return_value=mem)
        manager.update_memory = AsyncMock()
        manager.config = MagicMock()

        result = await rollback_last_consolidation(manager)
        assert result.rolled_back == 1
        manager.update_memory.assert_called_once_with(
            "mem-1", content="original content", metadata={}
        )

    @pytest.mark.asyncio
    async def test_skip_conflict_memory(self) -> None:
        from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, SemanticMemory

        now = datetime.now(UTC)
        event = EpisodicMemory(
            content="consolidation\n[affected_ids:mem-1]",
            event_type="consolidation",
            user_id="test",
        )
        object.__setattr__(event, "created_at", now - timedelta(minutes=5))

        mem = SemanticMemory(
            content="manually changed",
            user_id="test",
            importance=0.9,
            metadata={"previous_content": "old"},
        )
        object.__setattr__(mem, "updated_at", now)

        manager = AsyncMock()
        manager.list_memories = AsyncMock(return_value=[event])
        manager.get_memory = AsyncMock(return_value=mem)
        manager.config = MagicMock()

        result = await rollback_last_consolidation(manager)
        assert result.rolled_back == 0
        assert result.skipped_conflict == 1
        assert "mem-1" in result.conflict_ids

    @pytest.mark.asyncio
    async def test_deleted_memory_skipped(self) -> None:
        from myrm_agent_harness.toolkits.memory.types import EpisodicMemory

        now = datetime.now(UTC)
        event = EpisodicMemory(
            content="consolidation\n[affected_ids:deleted-mem]",
            event_type="consolidation",
            user_id="test",
        )
        object.__setattr__(event, "created_at", now)

        manager = AsyncMock()
        manager.list_memories = AsyncMock(return_value=[event])
        manager.get_memory = AsyncMock(return_value=None)
        manager.config = MagicMock()

        result = await rollback_last_consolidation(manager)
        assert result.rolled_back == 0
        assert result.errors == 0

    @pytest.mark.asyncio
    async def test_exception_handling(self) -> None:
        from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, SemanticMemory

        now = datetime.now(UTC)
        event = EpisodicMemory(
            content="consolidation\n[affected_ids:mem-1]",
            event_type="consolidation",
            user_id="test",
        )
        object.__setattr__(event, "created_at", now)

        mem = SemanticMemory(
            content="content",
            user_id="test",
            importance=0.05,
            metadata={"consolidated": True},
        )
        object.__setattr__(mem, "updated_at", now - timedelta(seconds=1))

        manager = AsyncMock()
        manager.list_memories = AsyncMock(return_value=[event])
        manager.get_memory = AsyncMock(return_value=mem)
        manager.update_memory = AsyncMock(side_effect=RuntimeError("DB error"))
        manager.config = MagicMock()

        result = await rollback_last_consolidation(manager)
        assert result.errors == 1
        assert result.rolled_back == 0


class TestAffectedIdsCollection:
    @pytest.mark.asyncio
    async def test_merge_op_collects_all_ids(self) -> None:
        """MergeOp should collect both the new merged id and all demoted source ids."""
        from myrm_agent_harness.toolkits.memory.strategies.consolidation import (
            MergeOp,
            _execute_operations,
        )
        from myrm_agent_harness.toolkits.memory.types import SemanticMemory

        merged_mem = SemanticMemory(content="merged", user_id="t", importance=0.9)
        object.__setattr__(merged_mem, "id", "new-merged-id")

        manager = AsyncMock()
        manager.user_id = "t"
        manager.store = AsyncMock(return_value=merged_mem)
        manager.update_memory = AsyncMock()

        ops = [MergeOp(source_ids=["s1", "s2"], merged_content="merged", importance=0.9)]
        stats = await _execute_operations(ops, manager)

        assert "new-merged-id" in stats.affected_ids
        assert "s1" in stats.affected_ids
        assert "s2" in stats.affected_ids
        assert len(stats.affected_ids) == 3

    @pytest.mark.asyncio
    async def test_correct_op_collects_both_ids(self) -> None:
        """CorrectOp should collect both original id and new correction id."""
        from myrm_agent_harness.toolkits.memory.strategies.consolidation import (
            CorrectOp,
            _execute_operations,
        )
        from myrm_agent_harness.toolkits.memory.types import SemanticMemory

        existing = SemanticMemory(content="wrong", user_id="t", importance=0.7)
        correction = SemanticMemory(content="right", user_id="t", importance=0.9)
        object.__setattr__(correction, "id", "correction-id")

        manager = AsyncMock()
        manager.get_memory = AsyncMock(return_value=existing)
        manager.correct_memory = AsyncMock(return_value=correction)

        ops = [CorrectOp(memory_id="original-id", corrected_content="right")]
        stats = await _execute_operations(ops, manager, id_map={"original-id": "original-id"})

        assert "original-id" in stats.affected_ids
        assert "correction-id" in stats.affected_ids
        assert len(stats.affected_ids) == 2

    @pytest.mark.asyncio
    async def test_update_content_op_collects_id(self) -> None:
        """UpdateContentOp should collect the updated memory id."""
        from myrm_agent_harness.toolkits.memory.strategies.consolidation import (
            UpdateContentOp,
            _execute_operations,
        )
        from myrm_agent_harness.toolkits.memory.types import SemanticMemory

        existing = SemanticMemory(content="old", user_id="t", importance=0.5)
        manager = AsyncMock()
        manager.get_memory = AsyncMock(return_value=existing)
        manager.update_memory = AsyncMock()

        ops = [UpdateContentOp(memory_id="mem-1", new_content="new", importance=0.8)]
        stats = await _execute_operations(ops, manager, id_map={"mem-1": "mem-1"})

        assert "mem-1" in stats.affected_ids
        assert len(stats.affected_ids) == 1
