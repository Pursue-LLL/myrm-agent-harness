"""Tests for recurrence-triggered memory consolidation strategy."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.skill_agent import SkillAgent
from myrm_agent_harness.toolkits.memory.strategies.recurrence import (
    RecurrenceDetector,
    _is_important,
)
from myrm_agent_harness.toolkits.vector.base import SearchResult, VectorDocument


@pytest.fixture
def mock_embedding() -> AsyncMock:
    emb = AsyncMock()
    emb.dimension = 768
    emb.embed = AsyncMock(return_value=[0.1] * 768)
    emb.embed_batch = AsyncMock(return_value=[[0.1] * 768])
    return emb


@pytest.fixture
def mock_vector() -> AsyncMock:
    vec = AsyncMock()
    vec.ensure_collection = AsyncMock()
    vec.upsert = AsyncMock(return_value=["id1"])
    vec.search = AsyncMock(return_value=[])
    vec.count = AsyncMock(return_value=5)
    vec.scroll = AsyncMock(return_value=([], None))
    vec.delete = AsyncMock(return_value=1)
    return vec


@pytest.fixture
def detector(mock_embedding: AsyncMock, mock_vector: AsyncMock) -> RecurrenceDetector:
    return RecurrenceDetector(
        embedding=mock_embedding,
        vector=mock_vector,
        collection_prefix="test_memory",
        similarity_threshold=0.70,
        recurrence_k=3,
        buffer_capacity=100,
        importance_preemption=True,
    )


class TestRecurrenceDetector:
    @pytest.mark.asyncio
    async def test_empty_summary_returns_not_triggered(
        self, detector: RecurrenceDetector
    ) -> None:
        result = await detector.check_recurrence("")
        assert not result.triggered
        assert result.consolidated_content is None

    @pytest.mark.asyncio
    async def test_whitespace_only_summary_not_triggered(
        self, detector: RecurrenceDetector
    ) -> None:
        result = await detector.check_recurrence("   \n  ")
        assert not result.triggered

    @pytest.mark.asyncio
    async def test_importance_preemption_allergy(
        self, detector: RecurrenceDetector
    ) -> None:
        result = await detector.check_recurrence("I have a peanut allergy")
        assert result.triggered
        assert result.consolidated_content == "I have a peanut allergy"
        assert result.topic_summary == "importance_preemption"
        assert result.recurrence_count == 1

    @pytest.mark.asyncio
    async def test_importance_preemption_chinese(
        self, detector: RecurrenceDetector
    ) -> None:
        result = await detector.check_recurrence("我对花生过敏")
        assert result.triggered
        assert result.consolidated_content == "我对花生过敏"

    @pytest.mark.asyncio
    async def test_importance_preemption_disabled(
        self, mock_embedding: AsyncMock, mock_vector: AsyncMock
    ) -> None:
        det = RecurrenceDetector(
            embedding=mock_embedding,
            vector=mock_vector,
            collection_prefix="test",
            importance_preemption=False,
        )
        result = await det.check_recurrence("I have a peanut allergy")
        assert not result.triggered

    @pytest.mark.asyncio
    async def test_no_recurrence_below_threshold(
        self, detector: RecurrenceDetector, mock_vector: AsyncMock
    ) -> None:
        mock_vector.search.return_value = []  # 0 similar results
        result = await detector.check_recurrence("I like Python programming")
        assert not result.triggered
        assert result.recurrence_count == 1  # Only current

    @pytest.mark.asyncio
    async def test_recurrence_triggered_at_k(
        self, detector: RecurrenceDetector, mock_vector: AsyncMock
    ) -> None:
        similar_results = [
            SearchResult(
                document=VectorDocument(id=f"id_{i}", content=f"Python session {i}"),
                score=0.85,
            )
            for i in range(2)
        ]
        mock_vector.search.return_value = similar_results

        result = await detector.check_recurrence("I like Python programming")
        assert result.triggered
        assert result.recurrence_count == 3  # 2 similar + 1 current = k
        assert result.consolidated_content == "I like Python programming"

    @pytest.mark.asyncio
    async def test_recurrence_triggered_with_llm(
        self, detector: RecurrenceDetector, mock_vector: AsyncMock
    ) -> None:
        similar_results = [
            SearchResult(
                document=VectorDocument(id=f"id_{i}", content=f"Python task {i}"),
                score=0.80,
            )
            for i in range(3)
        ]
        mock_vector.search.return_value = similar_results

        async def mock_llm(system: str, user: str) -> str:
            return "User's primary programming language is Python"

        result = await detector.check_recurrence(
            "Writing Python again", llm_func=mock_llm
        )
        assert result.triggered
        assert result.consolidated_content == "User's primary programming language is Python"
        assert result.recurrence_count == 4

    @pytest.mark.asyncio
    async def test_llm_failure_fallback(
        self, detector: RecurrenceDetector, mock_vector: AsyncMock
    ) -> None:
        similar_results = [
            SearchResult(
                document=VectorDocument(id=f"id_{i}", content=f"topic {i}"),
                score=0.75,
            )
            for i in range(3)
        ]
        mock_vector.search.return_value = similar_results

        async def failing_llm(system: str, user: str) -> str:
            raise RuntimeError("LLM error")

        result = await detector.check_recurrence("topic again", llm_func=failing_llm)
        assert result.triggered
        assert result.consolidated_content == "topic again"

    @pytest.mark.asyncio
    async def test_eviction_when_over_capacity(
        self, detector: RecurrenceDetector, mock_vector: AsyncMock
    ) -> None:
        mock_vector.count.return_value = 150
        docs = [MagicMock(id=f"old_{i}") for i in range(50)]
        mock_vector.scroll.return_value = (docs, None)

        await detector.check_recurrence("normal topic")
        mock_vector.delete.assert_called()

    @pytest.mark.asyncio
    async def test_no_eviction_within_capacity(
        self, detector: RecurrenceDetector, mock_vector: AsyncMock
    ) -> None:
        mock_vector.count.return_value = 50
        mock_vector.search.return_value = []

        await detector.check_recurrence("normal topic")
        mock_vector.scroll.assert_not_called()

    @pytest.mark.asyncio
    async def test_collection_initialized_once(
        self, detector: RecurrenceDetector, mock_vector: AsyncMock
    ) -> None:
        mock_vector.search.return_value = []
        await detector.check_recurrence("topic 1")
        await detector.check_recurrence("topic 2")
        mock_vector.ensure_collection.assert_called_once()

    @pytest.mark.asyncio
    async def test_triggered_entries_deleted(
        self, detector: RecurrenceDetector, mock_vector: AsyncMock
    ) -> None:
        similar_results = [
            SearchResult(
                document=VectorDocument(id=f"triggered_{i}", content=f"recurrent topic {i}"),
                score=0.82,
            )
            for i in range(3)
        ]
        mock_vector.search.return_value = similar_results

        await detector.check_recurrence("recurrent topic again")
        delete_calls = mock_vector.delete.call_args_list
        triggered_ids = ["triggered_0", "triggered_1", "triggered_2"]
        assert any(
            call.args == (detector._collection, triggered_ids)
            for call in delete_calls
        )


    @pytest.mark.asyncio
    async def test_exactly_k_minus_one_does_not_trigger(
        self, mock_embedding: AsyncMock, mock_vector: AsyncMock
    ) -> None:
        """k=4, 2 similar results -> count=3 (2+1) < 4, should NOT trigger."""
        det = RecurrenceDetector(
            embedding=mock_embedding,
            vector=mock_vector,
            collection_prefix="test",
            recurrence_k=4,
        )
        similar_results = [
            SearchResult(
                document=VectorDocument(id=f"id_{i}", content=f"topic {i}"),
                score=0.80,
            )
            for i in range(2)
        ]
        mock_vector.search.return_value = similar_results
        result = await det.check_recurrence("some topic")
        assert not result.triggered
        assert result.recurrence_count == 3

    @pytest.mark.asyncio
    async def test_embedding_failure_propagates_to_caller(
        self, detector: RecurrenceDetector, mock_embedding: AsyncMock
    ) -> None:
        """If embedding fails, exception propagates (caught by manager layer)."""
        mock_embedding.embed.side_effect = RuntimeError("Embedding service down")
        with pytest.raises(RuntimeError, match="Embedding service down"):
            await detector.check_recurrence("test topic")

    @pytest.mark.asyncio
    async def test_search_results_with_empty_content_filtered(
        self, detector: RecurrenceDetector, mock_vector: AsyncMock
    ) -> None:
        """Empty-content search results should be filtered from consolidation snippets."""
        similar_results = [
            SearchResult(document=VectorDocument(id="id_0", content="topic A"), score=0.85),
            SearchResult(document=VectorDocument(id="id_1", content=""), score=0.75),
            SearchResult(document=VectorDocument(id="id_2", content="topic B"), score=0.80),
        ]
        mock_vector.search.return_value = similar_results

        consolidated_snippets: list[str] = []

        async def capture_llm(system: str, user: str) -> str:
            for line in user.split("\n"):
                if line.startswith("[Session"):
                    consolidated_snippets.append(line)
            return "consolidated result"

        result = await detector.check_recurrence("topic C", llm_func=capture_llm)
        assert result.triggered
        assert "[Session 1]: topic A" in "\n".join(consolidated_snippets)
        assert "[Session 2]: topic B" in "\n".join(consolidated_snippets)
        assert "]: " not in "\n".join(consolidated_snippets).replace("[Session 1]: topic A", "").replace("[Session 2]: topic B", "").replace("[Session 3]: topic C", "")

    @pytest.mark.asyncio
    async def test_vector_upsert_called_with_correct_collection(
        self, detector: RecurrenceDetector, mock_vector: AsyncMock
    ) -> None:
        """Verify upsert uses the correct collection name."""
        mock_vector.search.return_value = []
        await detector.check_recurrence("test topic")
        assert mock_vector.upsert.call_args[0][0] == "test_memory_recurrence_buffer"


class TestIsImportant:
    def test_english_allergy(self) -> None:
        assert _is_important("I have a severe allergy to shellfish")

    def test_english_password(self) -> None:
        assert _is_important("My password for the server is")

    def test_english_medication(self) -> None:
        assert _is_important("I take medication for blood pressure")

    def test_chinese_allergy(self) -> None:
        assert _is_important("我对花生过敏很严重")

    def test_chinese_urgency(self) -> None:
        assert _is_important("这个截止日期很紧急")

    def test_normal_text_not_important(self) -> None:
        assert not _is_important("I like reading books about history")

    def test_chinese_normal_not_important(self) -> None:
        assert not _is_important("今天天气不错，适合散步")

    def test_case_insensitive(self) -> None:
        assert _is_important("I have DIABETES type 2")

    def test_disability_keyword(self) -> None:
        assert _is_important("I use a wheelchair")


class TestBuildRecurrenceSummary:
    """Test SkillAgent._build_recurrence_summary static method."""

    def test_string_query(self) -> None:
        result = SkillAgent._build_recurrence_summary("Help me write Python", [])
        assert result == "Help me write Python"

    def test_string_query_truncated_at_300(self) -> None:
        long_query = "x" * 500
        result = SkillAgent._build_recurrence_summary(long_query, [])
        assert len(result) == 300

    def test_list_query_extracts_user_messages(self) -> None:
        query = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "Help with Python"},
        ]
        result = SkillAgent._build_recurrence_summary(query, [])
        assert "Hello" in result
        assert "Help with Python" in result
        assert "Hi there" not in result

    def test_empty_string_returns_empty(self) -> None:
        result = SkillAgent._build_recurrence_summary("", [])
        assert result == ""

    def test_whitespace_only_returns_empty(self) -> None:
        result = SkillAgent._build_recurrence_summary("   ", [])
        assert result == ""

    def test_non_string_non_list_returns_empty(self) -> None:
        result = SkillAgent._build_recurrence_summary(12345, [])
        assert result == ""

    def test_list_with_no_user_messages_returns_empty(self) -> None:
        query = [
            {"role": "assistant", "content": "I can help"},
            {"role": "system", "content": "You are helpful"},
        ]
        result = SkillAgent._build_recurrence_summary(query, [])
        assert result == ""
