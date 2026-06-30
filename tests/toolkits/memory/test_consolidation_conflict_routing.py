"""Tests for consolidation conflict routing in _execute_operations.

Covers:
- ConflictResolution enum values
- PendingRecord conflict fields (is_conflict, conflict_old_memory_id, etc.)
- ConflictContext dataclass fields
- CorrectOp routing decision: importance_thr / confidence_thr gates
- Each ConflictResolution branch: PENDING, KEEP_OLD, KEEP_NEW, MERGE, DISCARD_BOTH
- ConsolidationStats.routed_to_user counter
- Default thresholds when config is None
- Custom thresholds from ConsolidationConfig
"""

from __future__ import annotations

from dataclasses import fields as dc_fields
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.memory.strategies.consolidation import (
    ConflictContext,
    ConsolidationStats,
    CorrectOp,
    MergeOp,
    _execute_operations,
)
from myrm_agent_harness.toolkits.memory.types import (
    ConflictResolution,
    MemoryType,
    PendingRecord,
    SemanticMemory,
)


class TestConflictResolutionEnum:
    """Validates ConflictResolution enum values."""

    def test_all_values(self) -> None:
        assert set(ConflictResolution) == {
            ConflictResolution.KEEP_OLD,
            ConflictResolution.KEEP_NEW,
            ConflictResolution.MERGE,
            ConflictResolution.DISCARD_BOTH,
            ConflictResolution.PENDING,
        }

    def test_string_values(self) -> None:
        assert ConflictResolution.KEEP_OLD == "keep_old"
        assert ConflictResolution.KEEP_NEW == "keep_new"
        assert ConflictResolution.MERGE == "merge"
        assert ConflictResolution.DISCARD_BOTH == "discard_both"
        assert ConflictResolution.PENDING == "pending"

    def test_from_string(self) -> None:
        assert ConflictResolution("keep_old") == ConflictResolution.KEEP_OLD
        assert ConflictResolution("pending") == ConflictResolution.PENDING


class TestPendingRecordConflictFields:
    """Validates PendingRecord conflict-related fields."""

    def test_default_no_conflict(self) -> None:
        record = PendingRecord(memory_type=MemoryType.SEMANTIC, content="test")
        assert record.is_conflict is False
        assert record.conflict_old_memory_id is None
        assert record.conflict_old_content is None
        assert record.conflict_accuracy_score is None
        assert record.conflict_importance is None
        assert record.conflict_auto_resolve_at is None

    def test_conflict_fields_populated(self) -> None:
        auto_resolve = datetime.now(UTC)
        record = PendingRecord(
            memory_type=MemoryType.SEMANTIC,
            content="new content",
            is_conflict=True,
            conflict_old_memory_id="old-mem-1",
            conflict_old_content="old content",
            conflict_accuracy_score=0.7,
            conflict_importance=0.8,
            conflict_auto_resolve_at=auto_resolve,
        )
        assert record.is_conflict is True
        assert record.conflict_old_memory_id == "old-mem-1"
        assert record.conflict_old_content == "old content"
        assert record.conflict_accuracy_score == 0.7
        assert record.conflict_importance == 0.8
        assert record.conflict_auto_resolve_at == auto_resolve

    def test_status_resolved(self) -> None:
        record = PendingRecord(
            memory_type=MemoryType.SEMANTIC,
            content="test",
            status="resolved",
        )
        assert record.status == "resolved"

    def test_serialization_round_trip(self) -> None:
        record = PendingRecord(
            memory_type=MemoryType.SEMANTIC,
            content="conflict content",
            is_conflict=True,
            conflict_old_memory_id="old-1",
            conflict_accuracy_score=0.65,
        )
        data = record.model_dump()
        restored = PendingRecord.model_validate(data)
        assert restored.is_conflict is True
        assert restored.conflict_old_memory_id == "old-1"
        assert restored.conflict_accuracy_score == 0.65


class TestConflictContext:
    """Validates ConflictContext frozen dataclass structure."""

    def test_all_fields_present(self) -> None:
        ctx = ConflictContext(
            old_memory_id="old-1",
            old_content="Python is best",
            new_content="Rust is better",
            accuracy_score=0.7,
            importance=0.8,
            merge_suggestion="Python and Rust both have merits",
        )
        assert ctx.old_memory_id == "old-1"
        assert ctx.old_content == "Python is best"
        assert ctx.new_content == "Rust is better"
        assert ctx.accuracy_score == 0.7
        assert ctx.importance == 0.8
        assert ctx.merge_suggestion == "Python and Rust both have merits"

    def test_frozen(self) -> None:
        ctx = ConflictContext(
            old_memory_id="id",
            old_content="a",
            new_content="b",
            accuracy_score=0.5,
            importance=0.5,
            merge_suggestion="c",
        )
        with pytest.raises(AttributeError):
            ctx.old_memory_id = "changed"  # type: ignore[misc]

    def test_slot_count(self) -> None:
        expected_fields = {
            "old_memory_id",
            "old_content",
            "new_content",
            "accuracy_score",
            "importance",
            "merge_suggestion",
        }
        actual_fields = {f.name for f in dc_fields(ConflictContext)}
        assert actual_fields == expected_fields


class TestConsolidationStatsRoutedField:
    """Validates routed_to_user counter on ConsolidationStats."""

    def test_default_zero(self) -> None:
        stats = ConsolidationStats()
        assert stats.routed_to_user == 0

    def test_custom_value(self) -> None:
        stats = ConsolidationStats(routed_to_user=3)
        assert stats.routed_to_user == 3


def _make_manager_mock() -> AsyncMock:
    manager = AsyncMock()
    manager.user_id = "test-user"
    manager.store = AsyncMock(return_value=MagicMock(id="stored-id"))
    manager.get_memory = AsyncMock(return_value=SemanticMemory(content="old content"))
    manager.update_memory = AsyncMock()
    manager.correct_memory = AsyncMock(return_value=MagicMock(id="corrected-id"))
    return manager


class TestConflictRoutingDecision:
    """Tests the should_route gate: importance >= threshold AND accuracy < threshold."""

    @pytest.mark.asyncio
    async def test_no_callback_skips_routing(self) -> None:
        """Without on_conflict, corrections execute directly."""
        manager = _make_manager_mock()
        ops = [CorrectOp(memory_id="mem-1", corrected_content="new", importance=0.9, accuracy_score=0.5)]
        stats = await _execute_operations(ops, manager, on_conflict=None)
        assert stats.routed_to_user == 0
        assert stats.corrected == 1

    @pytest.mark.asyncio
    async def test_low_importance_skips_routing(self) -> None:
        """importance < threshold → direct correction, no routing."""
        callback = AsyncMock(return_value=ConflictResolution.PENDING)
        manager = _make_manager_mock()
        ops = [CorrectOp(memory_id="mem-1", corrected_content="new", importance=0.3, accuracy_score=0.5)]
        stats = await _execute_operations(ops, manager, on_conflict=callback)
        callback.assert_not_called()
        assert stats.corrected == 1

    @pytest.mark.asyncio
    async def test_high_accuracy_skips_routing(self) -> None:
        """accuracy >= threshold → confident correction, no routing."""
        callback = AsyncMock(return_value=ConflictResolution.PENDING)
        manager = _make_manager_mock()
        ops = [CorrectOp(memory_id="mem-1", corrected_content="new", importance=0.9, accuracy_score=0.95)]
        stats = await _execute_operations(ops, manager, on_conflict=callback)
        callback.assert_not_called()
        assert stats.corrected == 1

    @pytest.mark.asyncio
    async def test_triggers_routing(self) -> None:
        """importance >= 0.6 AND accuracy < 0.85 → routes to callback."""
        callback = AsyncMock(return_value=ConflictResolution.PENDING)
        manager = _make_manager_mock()
        ops = [CorrectOp(memory_id="mem-1", corrected_content="new", importance=0.8, accuracy_score=0.6)]
        stats = await _execute_operations(ops, manager, on_conflict=callback)
        callback.assert_called_once()
        assert stats.routed_to_user == 1
        assert stats.corrected == 0


class TestConflictResolutionBranches:
    """Tests each ConflictResolution outcome from the callback."""

    @pytest.mark.asyncio
    async def test_pending_skips_execution(self) -> None:
        callback = AsyncMock(return_value=ConflictResolution.PENDING)
        manager = _make_manager_mock()
        ops = [CorrectOp(memory_id="mem-1", corrected_content="new", importance=0.8, accuracy_score=0.5)]
        stats = await _execute_operations(ops, manager, on_conflict=callback)
        assert stats.routed_to_user == 1
        assert stats.corrected == 0
        manager.correct_memory.assert_not_called()
        manager.update_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_keep_old_skips_execution(self) -> None:
        callback = AsyncMock(return_value=ConflictResolution.KEEP_OLD)
        manager = _make_manager_mock()
        ops = [CorrectOp(memory_id="mem-1", corrected_content="new", importance=0.8, accuracy_score=0.5)]
        stats = await _execute_operations(ops, manager, on_conflict=callback)
        assert stats.routed_to_user == 0
        assert stats.corrected == 0
        manager.correct_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_keep_new_executes_correction(self) -> None:
        callback = AsyncMock(return_value=ConflictResolution.KEEP_NEW)
        manager = _make_manager_mock()
        ops = [CorrectOp(memory_id="mem-1", corrected_content="new", importance=0.8, accuracy_score=0.5)]
        stats = await _execute_operations(ops, manager, on_conflict=callback)
        assert stats.corrected == 1
        manager.correct_memory.assert_called_once()

    @pytest.mark.asyncio
    async def test_merge_executes_correction(self) -> None:
        callback = AsyncMock(return_value=ConflictResolution.MERGE)
        manager = _make_manager_mock()
        ops = [CorrectOp(memory_id="mem-1", corrected_content="merged", importance=0.8, accuracy_score=0.5)]
        stats = await _execute_operations(ops, manager, on_conflict=callback)
        assert stats.corrected == 1
        manager.correct_memory.assert_called_once()

    @pytest.mark.asyncio
    async def test_discard_both_demotes(self) -> None:
        callback = AsyncMock(return_value=ConflictResolution.DISCARD_BOTH)
        manager = _make_manager_mock()
        ops = [CorrectOp(memory_id="mem-1", corrected_content="new", importance=0.8, accuracy_score=0.5)]
        stats = await _execute_operations(ops, manager, on_conflict=callback)
        assert stats.corrected == 1
        manager.update_memory.assert_called_once_with("mem-1", importance=0.01)
        manager.correct_memory.assert_not_called()


class TestConflictCallbackContext:
    """Verifies the ConflictContext passed to the callback has correct values."""

    @pytest.mark.asyncio
    async def test_context_fields(self) -> None:
        captured_ctx: list[ConflictContext] = []

        async def capture_callback(ctx: ConflictContext) -> ConflictResolution:
            captured_ctx.append(ctx)
            return ConflictResolution.PENDING

        manager = _make_manager_mock()
        existing = SemanticMemory(content="old fact about Python")
        manager.get_memory = AsyncMock(return_value=existing)

        ops = [
            CorrectOp(
                memory_id="mem-1",
                corrected_content="new fact about Rust",
                importance=0.9,
                accuracy_score=0.6,
            )
        ]
        await _execute_operations(ops, manager, on_conflict=capture_callback)

        assert len(captured_ctx) == 1
        ctx = captured_ctx[0]
        assert ctx.old_memory_id == "mem-1"
        assert ctx.old_content == "old fact about Python"
        assert ctx.new_content == "new fact about Rust"
        assert ctx.accuracy_score == 0.6
        assert ctx.importance == 0.9
        assert ctx.merge_suggestion == "new fact about Rust"


class TestCustomThresholds:
    """Tests that ConsolidationConfig thresholds override defaults."""

    @pytest.mark.asyncio
    async def test_custom_importance_threshold(self) -> None:
        from myrm_agent_harness.toolkits.memory.config import ConsolidationConfig

        config = ConsolidationConfig(conflict_importance_threshold=0.9)
        callback = AsyncMock(return_value=ConflictResolution.PENDING)
        manager = _make_manager_mock()
        ops = [CorrectOp(memory_id="mem-1", corrected_content="new", importance=0.8, accuracy_score=0.5)]
        stats = await _execute_operations(ops, manager, on_conflict=callback, config=config)
        callback.assert_not_called()
        assert stats.corrected == 1

    @pytest.mark.asyncio
    async def test_custom_confidence_threshold(self) -> None:
        from myrm_agent_harness.toolkits.memory.config import ConsolidationConfig

        config = ConsolidationConfig(conflict_confidence_threshold=0.5)
        callback = AsyncMock(return_value=ConflictResolution.PENDING)
        manager = _make_manager_mock()
        ops = [CorrectOp(memory_id="mem-1", corrected_content="new", importance=0.8, accuracy_score=0.6)]
        stats = await _execute_operations(ops, manager, on_conflict=callback, config=config)
        callback.assert_not_called()
        assert stats.corrected == 1


class TestMergeOpUnaffectedByConflictCallback:
    """MergeOp never routes to on_conflict — only CorrectOp does."""

    @pytest.mark.asyncio
    async def test_merge_ignores_callback(self) -> None:
        callback = AsyncMock(return_value=ConflictResolution.PENDING)
        manager = _make_manager_mock()
        ops = [MergeOp(source_ids=["a", "b"], merged_content="merged")]
        stats = await _execute_operations(ops, manager, on_conflict=callback)
        callback.assert_not_called()
        assert stats.merged == 1
        assert stats.routed_to_user == 0


class TestLockedRuleSkipsConflict:
    """User-locked procedural rules bypass conflict routing entirely."""

    @pytest.mark.asyncio
    async def test_locked_rule_skips(self) -> None:
        callback = AsyncMock(return_value=ConflictResolution.PENDING)
        manager = _make_manager_mock()
        locked = MagicMock()
        locked.is_user_locked = True
        locked.content = "locked rule"
        manager.get_memory = AsyncMock(return_value=locked)
        ops = [CorrectOp(memory_id="mem-1", corrected_content="new", importance=0.9, accuracy_score=0.5)]
        stats = await _execute_operations(ops, manager, on_conflict=callback)
        callback.assert_not_called()
        assert stats.corrected == 0
        assert stats.routed_to_user == 0


class TestIdMapResolution:
    """Tests that short IDs in CorrectOp are resolved through id_map."""

    @pytest.mark.asyncio
    async def test_short_id_resolved(self) -> None:
        callback = AsyncMock(return_value=ConflictResolution.PENDING)
        manager = _make_manager_mock()
        id_map = {"short-id": "full-uuid-1234-5678-abcd"}
        ops = [CorrectOp(memory_id="short-id", corrected_content="new", importance=0.9, accuracy_score=0.5)]
        stats = await _execute_operations(ops, manager, id_map, on_conflict=callback)

        ctx = callback.call_args[0][0]
        assert ctx.old_memory_id == "full-uuid-1234-5678-abcd"


class TestNonSemanticMemoryCorrection:
    """When existing is not SemanticMemory, uses update_memory instead of correct_memory."""

    @pytest.mark.asyncio
    async def test_non_semantic_uses_update(self) -> None:
        manager = _make_manager_mock()
        non_semantic = MagicMock()
        non_semantic.content = "old rule"
        non_semantic.is_user_locked = False
        manager.get_memory = AsyncMock(return_value=non_semantic)
        ops = [CorrectOp(memory_id="mem-1", corrected_content="updated rule", importance=0.3, accuracy_score=0.95)]
        stats = await _execute_operations(ops, manager, on_conflict=None)
        assert stats.updated == 1
        assert stats.corrected == 0
        manager.update_memory.assert_called_once_with("mem-1", content="updated rule")
        manager.correct_memory.assert_not_called()


class TestCallbackExceptionHandling:
    """Callback exception is caught by the outer try/except, incrementing errors."""

    @pytest.mark.asyncio
    async def test_callback_exception_increments_errors(self) -> None:
        async def failing_callback(ctx: object) -> ConflictResolution:
            raise RuntimeError("callback crashed")

        manager = _make_manager_mock()
        ops = [CorrectOp(memory_id="mem-1", corrected_content="new", importance=0.9, accuracy_score=0.5)]
        stats = await _execute_operations(ops, manager, on_conflict=failing_callback)
        assert stats.errors == 1
        assert stats.corrected == 0
        assert stats.routed_to_user == 0


class TestMultipleOpsInBatch:
    """Multiple CorrectOps with mixed routing decisions."""

    @pytest.mark.asyncio
    async def test_mixed_routing(self) -> None:
        call_count = 0

        async def alternating_callback(ctx: object) -> ConflictResolution:
            nonlocal call_count
            call_count += 1
            return ConflictResolution.PENDING if call_count == 1 else ConflictResolution.KEEP_NEW

        manager = _make_manager_mock()
        ops = [
            CorrectOp(memory_id="mem-1", corrected_content="new1", importance=0.9, accuracy_score=0.5),
            CorrectOp(memory_id="mem-2", corrected_content="new2", importance=0.3, accuracy_score=0.5),
            CorrectOp(memory_id="mem-3", corrected_content="new3", importance=0.8, accuracy_score=0.6),
        ]
        stats = await _execute_operations(ops, manager, on_conflict=alternating_callback)
        assert stats.routed_to_user == 1
        assert stats.corrected == 2
        assert call_count == 2


class TestBoundaryThresholds:
    """Exact boundary values for importance and accuracy thresholds."""

    @pytest.mark.asyncio
    async def test_exact_importance_threshold_triggers(self) -> None:
        """importance == 0.6 (exactly at threshold) should trigger routing."""
        callback = AsyncMock(return_value=ConflictResolution.PENDING)
        manager = _make_manager_mock()
        ops = [CorrectOp(memory_id="mem-1", corrected_content="new", importance=0.6, accuracy_score=0.5)]
        stats = await _execute_operations(ops, manager, on_conflict=callback)
        callback.assert_called_once()
        assert stats.routed_to_user == 1

    @pytest.mark.asyncio
    async def test_exact_accuracy_threshold_skips(self) -> None:
        """accuracy == 0.85 (exactly at threshold) should NOT trigger routing."""
        callback = AsyncMock(return_value=ConflictResolution.PENDING)
        manager = _make_manager_mock()
        ops = [CorrectOp(memory_id="mem-1", corrected_content="new", importance=0.9, accuracy_score=0.85)]
        stats = await _execute_operations(ops, manager, on_conflict=callback)
        callback.assert_not_called()
        assert stats.corrected == 1

    @pytest.mark.asyncio
    async def test_just_below_accuracy_triggers(self) -> None:
        """accuracy == 0.84 (just below threshold) should trigger routing."""
        callback = AsyncMock(return_value=ConflictResolution.PENDING)
        manager = _make_manager_mock()
        ops = [CorrectOp(memory_id="mem-1", corrected_content="new", importance=0.9, accuracy_score=0.84)]
        stats = await _execute_operations(ops, manager, on_conflict=callback)
        callback.assert_called_once()
        assert stats.routed_to_user == 1

    @pytest.mark.asyncio
    async def test_just_below_importance_skips(self) -> None:
        """importance == 0.59 (just below threshold) should skip routing."""
        callback = AsyncMock(return_value=ConflictResolution.PENDING)
        manager = _make_manager_mock()
        ops = [CorrectOp(memory_id="mem-1", corrected_content="new", importance=0.59, accuracy_score=0.5)]
        stats = await _execute_operations(ops, manager, on_conflict=callback)
        callback.assert_not_called()
        assert stats.corrected == 1


class TestConsolidationConfigFields:
    """Tests ConsolidationConfig conflict-related fields."""

    def test_default_thresholds(self) -> None:
        from myrm_agent_harness.toolkits.memory.config import ConsolidationConfig

        cfg = ConsolidationConfig()
        assert cfg.conflict_importance_threshold == 0.6
        assert cfg.conflict_confidence_threshold == 0.85
        assert cfg.conflict_auto_resolve_days == 7
