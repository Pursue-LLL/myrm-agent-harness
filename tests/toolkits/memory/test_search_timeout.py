"""Tests for memory retrieval wall-clock timeout (fail-open degradation).

Verifies that a hanging remote store (embedding / vector) is cut at the shared
deadline, partial results are retained, and the search is marked degraded instead
of blocking the agent turn indefinitely.
"""

import asyncio

import pytest

from myrm_agent_harness.toolkits.memory.config import MemoryConfig, RetrievalConfig
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.metrics import SearchMetrics, get_search_metrics
from myrm_agent_harness.toolkits.memory.types import MemoryType


@pytest.fixture
def fast_timeout_config() -> MemoryConfig:
    """Memory config with a tiny timeout so tests exercise the deadline cheaply."""
    return MemoryConfig(
        embedding_model="test-model",
        collection_prefix="test_memory",
        retrieval=RetrievalConfig(timeout_seconds=0.05),
    )


async def _hang(seconds: float) -> list[object]:
    await asyncio.sleep(seconds)
    return []


async def _hang_forever(*args: object, **kwargs: object) -> list[object]:
    """Async side-effect that outlives the tiny test timeout."""
    await asyncio.sleep(0.5)
    return []


class TestRetrievalTimeoutConfig:
    def test_default_timeout_seconds(self) -> None:
        assert RetrievalConfig().timeout_seconds == 10.0

    def test_configurable_timeout_seconds(self) -> None:
        assert RetrievalConfig(timeout_seconds=2.5).timeout_seconds == 2.5


class TestCollectPartialResults:
    @pytest.mark.asyncio
    async def test_hanging_store_keeps_fast_results_and_marks_degraded(
        self, mock_relational_store, mock_vector_store, mock_embedding, fast_timeout_config
    ) -> None:
        """A hanging semantic search degrades recall but keeps the fast profile results."""
        from myrm_agent_harness.toolkits.memory.types import ProfileEntry

        mock_relational_store.list_profiles.return_value = [
            ProfileEntry(key="timezone", value="UTC+8"),
        ]
        mock_embedding.embed.return_value = [0.1] * 768
        mock_vector_store.count.return_value = 1
        mock_vector_store.search.side_effect = _hang_forever

        manager = MemoryManager(
            fast_timeout_config,
            user_id="test_user",
            relational=mock_relational_store,
            vector=mock_vector_store,
            embedding=mock_embedding,
            auto_warmup=False,
        )

        results = await manager.search(
            "timezone", memory_types=[MemoryType.PROFILE, MemoryType.SEMANTIC], limit=10, use_rrf=False
        )

        assert len(results) == 1
        assert results[0].memory_type == MemoryType.PROFILE
        assert manager.last_retrieval_trace is not None
        assert manager.last_retrieval_trace.degraded is True

    @pytest.mark.asyncio
    async def test_all_stores_hanging_returns_empty_without_raising(
        self, mock_relational_store, fast_timeout_config
    ) -> None:
        """A single hanging relational store yields an empty, degraded search, not an exception."""
        mock_relational_store.search_rules.side_effect = _hang_forever

        manager = MemoryManager(
            fast_timeout_config,
            user_id="test_user",
            relational=mock_relational_store,
            auto_warmup=False,
        )

        results = await manager.search(
            "trigger", memory_types=[MemoryType.PROCEDURAL], limit=10, use_rrf=False
        )

        assert results == []
        assert manager.last_retrieval_trace is not None
        assert manager.last_retrieval_trace.degraded is True

    @pytest.mark.asyncio
    async def test_no_backend_yields_empty_without_error(
        self, fast_timeout_config
    ) -> None:
        """No relational/vector backend means no tasks: empty, non-degraded search."""
        manager = MemoryManager(
            fast_timeout_config,
            user_id="test_user",
            auto_warmup=False,
        )

        results = await manager.search(
            "anything", memory_types=[MemoryType.SEMANTIC], limit=10, use_rrf=False
        )

        assert results == []
        assert manager.last_retrieval_trace is not None
        assert manager.last_retrieval_trace.degraded is False


class TestEmbedTimeoutFailOpen:
    @pytest.mark.asyncio
    async def test_hanging_embedding_fails_open_to_local_only(
        self, mock_vector_store, mock_embedding, fast_timeout_config
    ) -> None:
        """An embedding hang must not block the turn: vector recall degrades, no exception."""
        mock_embedding.embed.side_effect = _hang_forever
        mock_vector_store.count.return_value = 1
        mock_vector_store.search.return_value = []

        manager = MemoryManager(
            fast_timeout_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            auto_warmup=False,
        )

        results = await manager.search(
            "weather", memory_types=[MemoryType.SEMANTIC], limit=10, use_rrf=False
        )

        assert results == []
        trace = manager.last_retrieval_trace
        assert trace is not None
        assert trace.degraded is True
        embed_step = next(step for step in trace.steps if step.phase == "embed")
        assert embed_step.status == "warning"


class TestDegradationMetrics:
    def test_record_degradation_counts(self) -> None:
        metrics = SearchMetrics()
        metrics.record_degradation("timeout")
        metrics.record_degradation("timeout")
        metrics.record_degradation("error")

        snapshot = metrics.snapshot()
        assert snapshot.degradation_timeout_count == 2
        assert snapshot.degradation_error_count == 1

    @pytest.mark.asyncio
    async def test_collect_timeout_increments_global_metrics(
        self, mock_relational_store, fast_timeout_config
    ) -> None:
        """A collect timeout must be observable through the global search metrics."""
        metrics = get_search_metrics()
        before = metrics.snapshot().degradation_timeout_count

        mock_relational_store.search_rules.side_effect = _hang_forever
        manager = MemoryManager(
            fast_timeout_config,
            user_id="test_user",
            relational=mock_relational_store,
            auto_warmup=False,
        )
        await manager.search(
            "trigger", memory_types=[MemoryType.PROCEDURAL], limit=10, use_rrf=False
        )

        assert metrics.snapshot().degradation_timeout_count == before + 1


class TestWikiSessionsCorpusTimeout:
    """memory_search_tool wiki/sessions branches must share the same wall-clock
    fail-open guarantee as the memory corpus (Art45 recall timeout DoD)."""

    @pytest.mark.asyncio
    async def test_wiki_corpus_hang_fails_open_with_notice(self) -> None:
        from unittest.mock import AsyncMock

        from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_execution import (
            search_wiki_corpus,
        )
        from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_policy import (
            MemorySearchBackends,
        )

        backends = MemorySearchBackends(
            query_wiki=AsyncMock(side_effect=_hang_forever)
        )
        text = await search_wiki_corpus(backends, "query", timeout_seconds=0.05)

        assert "timed out" in text.lower()
        assert "retry" in text.lower()

    @pytest.mark.asyncio
    async def test_sessions_corpus_hang_fails_open_with_notice(self) -> None:
        from unittest.mock import AsyncMock

        from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_execution import (
            search_sessions_corpus,
        )
        from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_policy import (
            MemorySearchBackends,
        )

        provider = AsyncMock()
        provider.search.side_effect = _hang_forever
        backends = MemorySearchBackends(conversation_provider=provider)
        text = await search_sessions_corpus(
            backends,
            query="q",
            limit=5,
            since=None,
            until=None,
            timeout_seconds=0.05,
        )

        assert "timed out" in text.lower()
        assert "retry" in text.lower()

    @pytest.mark.asyncio
    async def test_web_corpus_hang_fails_open_with_notice(self) -> None:
        from unittest.mock import AsyncMock

        from myrm_agent_harness.toolkits.memory.agent_surface.memory_agent_tools import (
            _search_web_corpus,
        )
        from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_policy import (
            MemorySearchBackends,
        )

        backends = MemorySearchBackends(
            query_web_corpus=AsyncMock(side_effect=_hang_forever)
        )
        text = await _search_web_corpus(
            backends, "query", 5, timeout_seconds=0.05
        )

        assert "timed out" in text.lower()
        assert "retry" in text.lower()
