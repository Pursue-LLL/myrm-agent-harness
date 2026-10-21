"""Evaluation suite for RecurrenceDetector and LocalWorkingMemoryBlock."""


from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.context_management.working_memory.block import (
    LocalWorkingMemoryBlock,
)
from myrm_agent_harness.agent.context_management.working_memory.types import (
    SubtaskStatus,
)
from myrm_agent_harness.toolkits.memory.consolidation import WorkingMemorySnapshot
from myrm_agent_harness.toolkits.memory.strategies.recurrence import (
    RecurrenceDetector,
    _is_trivial_summary,
)
from myrm_agent_harness.toolkits.vector.base import SearchResult, VectorDocument

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_embedding() -> AsyncMock:
    emb = AsyncMock()
    emb.dimension = 768
    emb.embed = AsyncMock(return_value=[0.05] * 768)
    emb.embed_batch = AsyncMock(return_value=[[0.05] * 768])
    return emb


@pytest.fixture
def mock_vector() -> AsyncMock:
    vec = AsyncMock()
    vec.ensure_collection = AsyncMock()
    vec.upsert = AsyncMock(return_value=["doc-id-1"])
    vec.search = AsyncMock(return_value=[])
    vec.count = AsyncMock(return_value=3)
    vec.scroll = AsyncMock(return_value=([], None))
    vec.delete = AsyncMock(return_value=1)
    return vec


@pytest.fixture
def detector(mock_embedding: AsyncMock, mock_vector: AsyncMock) -> RecurrenceDetector:
    return RecurrenceDetector(
        embedding=mock_embedding,
        vector=mock_vector,
        collection_prefix="test_memory",
        similarity_threshold=0.75,
        recurrence_k=2,
        buffer_capacity=10,
        soft_deprecation=True,
    )


# ---------------------------------------------------------------------------
# 1. RecurrenceDetector Enhancements Test
# ---------------------------------------------------------------------------


class TestRecurrenceDetectorEnhancements:
    def test_trivial_greeting_detection(self) -> None:
        assert _is_trivial_summary("hello")
        assert _is_trivial_summary("Hi there!")
        assert _is_trivial_summary("你好呀")
        assert _is_trivial_summary("好的，收到")
        assert _is_trivial_summary("Thanks a lot")
        assert not _is_trivial_summary("User prefers TypeScript with strict mode enabled")
        assert not _is_trivial_summary(
            "Database connection timeout occurs under 100 concurrent clients"
        )

    @pytest.mark.asyncio
    async def test_trivial_greeting_short_circuits_no_vector_call(
        self,
        detector: RecurrenceDetector,
        mock_vector: AsyncMock,
        mock_embedding: AsyncMock,
    ) -> None:
        result = await detector.check_recurrence("你好")
        assert not result.triggered
        assert result.consolidated_content is None
        mock_embedding.embed.assert_not_called()
        mock_vector.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_soft_deprecation_flow_preserves_lineage(
        self, detector: RecurrenceDetector, mock_vector: AsyncMock
    ) -> None:
        existing_doc = VectorDocument(
            id="hist-doc-1",
            content="User prefers async python code",
            vector=[0.05] * 768,
            metadata={"session_id": "sess-old", "importance": 0.5, "is_deprecated": False},
        )
        mock_vector.search.return_value = [
            SearchResult(document=existing_doc, score=0.88)
        ]

        mock_llm = AsyncMock(
            return_value="Consolidated: User strictly prefers asyncio over threading"
        )
        result = await detector.check_recurrence(
            "User prefers async python everywhere", llm_func=mock_llm
        )
        assert result.triggered
        assert "asyncio" in str(result.consolidated_content)

        # Vector delete should NOT be called because soft_deprecation=True
        mock_vector.delete.assert_not_called()

        # Vector upsert should have been called twice:
        # 1. Updating hist-doc-1 with is_deprecated=True
        # 2. Saving the new entry
        assert mock_vector.upsert.call_count >= 2

    @pytest.mark.asyncio
    async def test_vector_search_filters_deprecated_entries(
        self, detector: RecurrenceDetector, mock_vector: AsyncMock
    ) -> None:
        deprecated_doc = VectorDocument(
            id="hist-doc-deprecated",
            content="User prefers async python code",
            vector=[0.05] * 768,
            metadata={"is_deprecated": True, "superseded_by": "new-doc-1"},
        )
        mock_vector.search.return_value = [
            SearchResult(document=deprecated_doc, score=0.92)
        ]
        result = await detector.check_recurrence("User prefers async python code")
        # Since the hit was deprecated, effective hits should be 0 (< recurrence_k=2)
        assert not result.triggered


# ---------------------------------------------------------------------------
# 2. LocalWorkingMemoryBlock System Test
# ---------------------------------------------------------------------------


class TestLocalWorkingMemoryBlockSystem:
    def setup_method(self) -> None:
        LocalWorkingMemoryBlock.reset()

    def teardown_method(self) -> None:
        LocalWorkingMemoryBlock.reset()

    def test_step_lifecycle_and_milestones(self) -> None:
        state = LocalWorkingMemoryBlock.initialize(goal="Refactor Storage Engine")
        state.goal = "Migrate SQLite queries to parameterized CTE statements"

        s1 = LocalWorkingMemoryBlock.add_subtask("Audit legacy SQL queries")
        assert s1 is not None
        assert s1.status == SubtaskStatus.PENDING

        LocalWorkingMemoryBlock.update_subtask(s1.id, status=SubtaskStatus.IN_PROGRESS)
        assert state.subtasks[0].status == SubtaskStatus.IN_PROGRESS

        LocalWorkingMemoryBlock.update_subtask(
            s1.id, status=SubtaskStatus.COMPLETED, notes="Found 12 un-parameterized queries"
        )
        assert state.subtasks[0].status == SubtaskStatus.COMPLETED
        assert state.subtasks[0].notes == "Found 12 un-parameterized queries"

        LocalWorkingMemoryBlock.record_trap(
            "sql_syntax_error",
            "Raw string concatenation causes syntax errors with single quotes",
        )
        assert len(state.traps) == 1

        LocalWorkingMemoryBlock.set_scratchpad("compatibility", "Do not break SQLite 3.35 compatibility")
        assert len(state.scratchpad) == 1

    def test_prefix_cache_friendly_turn_tail_render(self) -> None:
        LocalWorkingMemoryBlock.initialize(goal="Ensure deterministic Markdown generation")
        LocalWorkingMemoryBlock.add_subtask("Step 1")
        LocalWorkingMemoryBlock.set_scratchpad("framework", "Myrmidon Harness")

        rendered = LocalWorkingMemoryBlock.format_turn_tail_markdown()
        assert "<working_board>" in rendered
        assert "</working_board>" in rendered
        assert "**Goal**: Ensure deterministic Markdown generation" in rendered
        assert "timestamp" not in rendered.lower()  # Protection against cache thrashing

    def test_to_working_memory_snapshot(self) -> None:
        LocalWorkingMemoryBlock.initialize(goal="Export to consolidation snapshot")
        s = LocalWorkingMemoryBlock.add_subtask("Build component")
        assert s is not None
        LocalWorkingMemoryBlock.update_subtask(s.id, SubtaskStatus.COMPLETED, notes="Component built successfully")
        LocalWorkingMemoryBlock.record_trap("concurrency_hazard", "Watch out for thread safety in async event loop")

        snapshot = LocalWorkingMemoryBlock.to_snapshot()
        assert isinstance(snapshot, WorkingMemorySnapshot)
        assert snapshot.goal == "Export to consolidation snapshot"
        assert len(snapshot.subtasks) == 1
        assert snapshot.subtasks[0].title == "Build component"
        assert snapshot.subtasks[0].completed is True
        assert len(snapshot.traps) == 1
        assert "thread safety" in snapshot.traps[0].avoidance_rule


# ---------------------------------------------------------------------------
# 3. Working-board retention & noise suppression
# ---------------------------------------------------------------------------


class TestWorkingBoardRetentionAndNoise:
    def teardown_method(self) -> None:
        LocalWorkingMemoryBlock.reset()

    def test_dimension_4_non_destructive_retention_rate(self) -> None:
        """Dim 4: Critical goal & traps survive multi-round working-board collapse."""
        LocalWorkingMemoryBlock.reset()
        state = LocalWorkingMemoryBlock.initialize(goal="Mission Critical Objective")
        LocalWorkingMemoryBlock.record_trap("safety_rule", "Critical memory safety rule")

        for round_idx in range(5):
            for step_idx in range(4):
                s = LocalWorkingMemoryBlock.add_subtask(f"Ephemeral step r{round_idx}-s{step_idx}")
                assert s is not None
                LocalWorkingMemoryBlock.update_subtask(s.id, SubtaskStatus.COMPLETED)
            active = LocalWorkingMemoryBlock.add_subtask(f"Active step r{round_idx}")
            assert active is not None
            LocalWorkingMemoryBlock.update_subtask(active.id, SubtaskStatus.IN_PROGRESS)

            rendered = LocalWorkingMemoryBlock.format_turn_tail_markdown(token_budget=10)
            # Render-time collapse must never destructively mutate state.
            assert state.goal == "Mission Critical Objective"
            assert any("Critical memory safety rule" in t.avoidance_rule for t in state.traps)
            assert f"Active step r{round_idx}" in rendered
            assert "prior completed subtasks collapsed]" in rendered

        assert len(state.traps) == 1

    def test_dimension_5_noise_suppression_ratio(self) -> None:
        """Dim 5: 100% noise rejection ratio on chitchat & greetings."""
        chitchat_samples = [
            "hello",
            "Hi there",
            "你好",
            "好的",
            "收到",
            "ok",
            "thank you",
            "thanks",
            " morning ",
            "bye!",
        ]
        suppressed = 0
        for sample in chitchat_samples:
            if _is_trivial_summary(sample):
                suppressed += 1

        suppression_ratio = suppressed / len(chitchat_samples)
        assert (
            suppression_ratio == 1.0
        ), f"Suppression ratio {suppression_ratio:.2%} is below 100%"
