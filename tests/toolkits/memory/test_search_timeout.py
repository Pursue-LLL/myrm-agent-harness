"""Tests for memory retrieval wall-clock timeout (fail-open degradation).

Verifies that a hanging remote store (embedding / vector) is cut at the shared
deadline, partial results are retained, and the search is marked degraded instead
of blocking the agent turn indefinitely.
"""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_policy import (
    MemorySearchBackends,
    MemorySearchPolicy,
)
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
        self,
        mock_relational_store,
        mock_vector_store,
        mock_embedding,
        fast_timeout_config,
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
            "timezone",
            memory_types=[MemoryType.PROFILE, MemoryType.SEMANTIC],
            limit=10,
            use_rrf=False,
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

        results = await manager.search("trigger", memory_types=[MemoryType.PROCEDURAL], limit=10, use_rrf=False)

        assert results == []
        assert manager.last_retrieval_trace is not None
        assert manager.last_retrieval_trace.degraded is True

    @pytest.mark.asyncio
    async def test_no_backend_yields_empty_without_error(self, fast_timeout_config) -> None:
        """No relational/vector backend means no tasks: empty, non-degraded search."""
        manager = MemoryManager(
            fast_timeout_config,
            user_id="test_user",
            auto_warmup=False,
        )

        results = await manager.search("anything", memory_types=[MemoryType.SEMANTIC], limit=10, use_rrf=False)

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

        results = await manager.search("weather", memory_types=[MemoryType.SEMANTIC], limit=10, use_rrf=False)

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
    async def test_collect_timeout_increments_global_metrics(self, mock_relational_store, fast_timeout_config) -> None:
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
        await manager.search("trigger", memory_types=[MemoryType.PROCEDURAL], limit=10, use_rrf=False)

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

        backends = MemorySearchBackends(query_wiki=AsyncMock(side_effect=_hang_forever))
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


class TestMemorySearchToolCorpusBranches:
    """memory_search_tool happy paths and boundary guards across wiki/sessions.

    Complements the timeout fail-open tests above by exercising the non-timeout
    branches: successful provider returns, empty-result notices, profile_key
    rejection, unavailable corpus guards, and single-corpus heading stripping.
    """

    @staticmethod
    def _build_tool(
        manager: MemoryManager,
        *,
        policy: MemorySearchPolicy | None = None,
        backends: MemorySearchBackends | None = None,
    ) -> object:
        from myrm_agent_harness.toolkits.memory.agent_surface.memory_agent_tools import (
            create_memory_tools,
        )
        from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_policy import (
            MemorySearchBackends,
            MemorySearchPolicy,
        )

        tools = create_memory_tools(
            manager,
            search_policy=policy or MemorySearchPolicy(),
            search_backends=backends or MemorySearchBackends(),
        )
        return next(t for t in tools if getattr(t, "name", None) == "memory_search_tool")

    @staticmethod
    def _manager(fast_timeout_config: MemoryConfig) -> MemoryManager:
        return MemoryManager(
            fast_timeout_config,
            user_id="test_user",
            auto_warmup=False,
        )

    @pytest.mark.asyncio
    async def test_wiki_corpus_happy_path_strips_heading(self, fast_timeout_config) -> None:
        from unittest.mock import AsyncMock

        from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_policy import (
            MemorySearchBackends,
            MemorySearchPolicy,
        )
        from myrm_agent_harness.toolkits.wiki.core.types import QueryResult

        backends = MemorySearchBackends(
            query_wiki=AsyncMock(
                return_value=QueryResult(
                    question="q",
                    answer="The wiki answer for the query.",
                    related_articles=[],
                )
            )
        )
        tool = self._build_tool(
            self._manager(fast_timeout_config),
            policy=MemorySearchPolicy(allow_wiki=True),
            backends=backends,
        )

        text = await tool.ainvoke({"query": "q", "corpus": "wiki"})

        assert "The wiki answer for the query." in text
        assert not text.startswith("## Wiki")

    @pytest.mark.asyncio
    async def test_sessions_corpus_happy_path(self, fast_timeout_config) -> None:
        from unittest.mock import AsyncMock

        from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_policy import (
            MemorySearchBackends,
            MemorySearchPolicy,
        )
        from myrm_agent_harness.toolkits.memory.conversation_search.types import (
            ConversationSearchHit,
            ConversationSearchResponse,
        )

        provider = AsyncMock()
        provider.search.return_value = ConversationSearchResponse(
            mode="search",
            hits=[
                ConversationSearchHit(
                    conversation_id="conv-1",
                    snippet="A matching conversation hit.",
                    score=0.85,
                )
            ],
        )
        tool = self._build_tool(
            self._manager(fast_timeout_config),
            policy=MemorySearchPolicy(allow_sessions=True),
            backends=MemorySearchBackends(conversation_provider=provider),
        )

        text = await tool.ainvoke({"query": "q", "corpus": "sessions"})

        assert "A matching conversation hit." in text

    @pytest.mark.asyncio
    async def test_profile_key_rejected_for_non_memory_corpus(self, fast_timeout_config) -> None:
        tool = self._build_tool(self._manager(fast_timeout_config))

        text = await tool.ainvoke({"query": "q", "corpus": "wiki", "profile_key": "timezone"})

        assert "profile_key lookup is only supported for corpus=memory." in text

    @pytest.mark.asyncio
    async def test_all_corpora_disabled_returns_no_corpora(self, fast_timeout_config, monkeypatch) -> None:
        import myrm_agent_harness.toolkits.memory.agent_surface.memory_agent_tools as tools_mod

        monkeypatch.setattr(
            tools_mod,
            "resolve_search_corpora",
            lambda corpus, policy: ([], None),
        )
        tool = self._build_tool(self._manager(fast_timeout_config))

        text = await tool.ainvoke({"query": "q", "corpus": "all"})

        assert text == "No search corpora available."

    @pytest.mark.asyncio
    async def test_wiki_corpus_unavailable_guard(self, fast_timeout_config) -> None:
        from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_policy import (
            MemorySearchBackends,
            MemorySearchPolicy,
        )

        tool = self._build_tool(
            self._manager(fast_timeout_config),
            policy=MemorySearchPolicy(allow_wiki=True),
            backends=MemorySearchBackends(),
        )

        text = await tool.ainvoke({"query": "q", "corpus": "wiki"})

        assert "Wiki search is not available." in text

    @pytest.mark.asyncio
    async def test_sessions_corpus_unavailable_guard(self, fast_timeout_config) -> None:
        from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_policy import (
            MemorySearchBackends,
            MemorySearchPolicy,
        )

        tool = self._build_tool(
            self._manager(fast_timeout_config),
            policy=MemorySearchPolicy(allow_sessions=True),
            backends=MemorySearchBackends(),
        )

        text = await tool.ainvoke({"query": "q", "corpus": "sessions"})

        assert "Conversation history search is not available." in text

    @pytest.mark.asyncio
    async def test_all_corpora_joins_sections(self, fast_timeout_config) -> None:
        from unittest.mock import AsyncMock

        from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_policy import (
            MemorySearchBackends,
            MemorySearchPolicy,
        )
        from myrm_agent_harness.toolkits.memory.conversation_search.types import (
            ConversationSearchHit,
            ConversationSearchResponse,
        )
        from myrm_agent_harness.toolkits.wiki.core.types import QueryResult

        provider = AsyncMock()
        provider.search.return_value = ConversationSearchResponse(
            mode="search",
            hits=[
                ConversationSearchHit(
                    conversation_id="conv-1",
                    snippet="A conversation hit.",
                    score=0.8,
                )
            ],
        )
        backends = MemorySearchBackends(
            query_wiki=AsyncMock(return_value=QueryResult(question="q", answer="Wiki answer.", related_articles=[])),
            conversation_provider=provider,
        )
        tool = self._build_tool(
            self._manager(fast_timeout_config),
            policy=MemorySearchPolicy(allow_wiki=True, allow_sessions=True),
            backends=backends,
        )

        text = await tool.ainvoke({"query": "q", "corpus": "all"})

        assert "## Memory" in text
        assert "## Wiki" in text
        assert "## Sessions" in text
        assert "## Web" not in text

    @pytest.mark.asyncio
    async def test_all_corpora_partial_timeout_keeps_survivors(self, fast_timeout_config) -> None:
        from unittest.mock import AsyncMock

        from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_policy import (
            MemorySearchBackends,
            MemorySearchPolicy,
        )
        from myrm_agent_harness.toolkits.memory.conversation_search.types import (
            ConversationSearchHit,
            ConversationSearchResponse,
        )

        provider = AsyncMock()
        provider.search.return_value = ConversationSearchResponse(
            mode="search",
            hits=[
                ConversationSearchHit(
                    conversation_id="conv-1",
                    snippet="A conversation hit.",
                    score=0.8,
                )
            ],
        )
        backends = MemorySearchBackends(
            query_wiki=AsyncMock(side_effect=_hang_forever),
            conversation_provider=provider,
        )
        tool = self._build_tool(
            self._manager(fast_timeout_config),
            policy=MemorySearchPolicy(allow_wiki=True, allow_sessions=True),
            backends=backends,
        )

        text = await tool.ainvoke({"query": "q", "corpus": "all"})

        assert "Wiki search timed out" in text
        assert "## Sessions" in text
        assert "A conversation hit." in text

    @pytest.mark.asyncio
    async def test_wiki_corpus_no_timeout_when_disabled(self, fast_timeout_config) -> None:
        from unittest.mock import AsyncMock

        from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_execution import (
            search_wiki_corpus,
        )
        from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_policy import (
            MemorySearchBackends,
        )
        from myrm_agent_harness.toolkits.wiki.core.types import QueryResult

        backends = MemorySearchBackends(
            query_wiki=AsyncMock(
                return_value=QueryResult(question="q", answer="Slow wiki answer.", related_articles=[])
            )
        )

        text = await search_wiki_corpus(backends, "q", timeout_seconds=None)

        assert "Slow wiki answer." in text

    @pytest.mark.asyncio
    async def test_stale_memory_with_code_path_emits_critical_notice(self) -> None:
        from datetime import UTC, datetime, timedelta
        from unittest.mock import AsyncMock, MagicMock, patch

        from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_execution import (
            search_memory_corpus,
        )
        from myrm_agent_harness.toolkits.memory.types import (
            MemorySearchResult,
            MemoryType,
            SemanticMemory,
        )

        old = datetime.now(UTC) - timedelta(days=30)
        stale = SemanticMemory(
            id="stale-1",
            content="Login flow lives in /Users/dev/server/auth/login.py",
            created_at=old,
            updated_at=old,
        )
        manager = AsyncMock()
        manager.search = AsyncMock(
            return_value=[MemorySearchResult(memory=stale, score=0.9, memory_type=MemoryType.SEMANTIC)]
        )
        manager.active_session = None
        manager.last_retrieval_trace = None
        manager.set_last_cited_memory_ids = MagicMock()

        with patch(
            "myrm_agent_harness.toolkits.memory.agent_surface.memory_search_execution.emit_cited_memory_ids",
            AsyncMock(),
        ):
            text = await search_memory_corpus(
                manager,
                query="login flow",
                category_to_type={"knowledge": MemoryType.SEMANTIC},
                categories=None,
                limit=5,
                since=None,
                until=None,
            )

        assert "CRITICAL: Outdated memory referencing potential paths" in text


class TestMemoryCorpusDegradedNotice:
    """memory corpus must tell the LLM when recall degraded but found nothing,
    matching the wiki/sessions corpora fail-open notice contract."""

    @pytest.mark.asyncio
    async def test_empty_plus_degraded_returns_timeout_notice(self) -> None:
        from datetime import UTC, datetime
        from unittest.mock import AsyncMock, MagicMock, patch

        from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_execution import (
            search_memory_corpus,
        )
        from myrm_agent_harness.toolkits.memory.observability import (
            MemoryRetrievalTrace,
        )
        from myrm_agent_harness.toolkits.memory.types import MemoryType

        manager = AsyncMock()
        manager.search = AsyncMock(return_value=[])
        manager.active_session = None
        manager.last_retrieval_trace = MemoryRetrievalTrace(
            id="trace-1",
            query_preview="pricing",
            occurred_at=datetime.now(UTC),
            degraded=True,
        )
        manager.set_last_cited_memory_ids = MagicMock()

        with patch(
            "myrm_agent_harness.toolkits.memory.agent_surface.memory_search_execution.emit_cited_memory_ids",
            AsyncMock(),
        ):
            text = await search_memory_corpus(
                manager,
                query="pricing",
                category_to_type={"knowledge": MemoryType.SEMANTIC},
                categories=None,
                limit=5,
                since=None,
                until=None,
            )

        assert "timed out" in text.lower()
        assert "retry" in text.lower()

    @pytest.mark.asyncio
    async def test_empty_without_degraded_returns_plain_notice(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_execution import (
            search_memory_corpus,
        )
        from myrm_agent_harness.toolkits.memory.types import MemoryType

        manager = AsyncMock()
        manager.search = AsyncMock(return_value=[])
        manager.active_session = None
        manager.last_retrieval_trace = None
        manager.set_last_cited_memory_ids = MagicMock()

        with patch(
            "myrm_agent_harness.toolkits.memory.agent_surface.memory_search_execution.emit_cited_memory_ids",
            AsyncMock(),
        ):
            text = await search_memory_corpus(
                manager,
                query="pricing",
                category_to_type={"knowledge": MemoryType.SEMANTIC},
                categories=None,
                limit=5,
                since=None,
                until=None,
            )

        assert text == "No relevant memories found."


class TestGraphEnrichTimeout:
    """Claim graph enrichment must fail open under the shared wall-clock deadline."""

    @pytest.mark.asyncio
    async def test_graph_enrich_hang_marks_degraded(
        self,
        mock_vector_store,
        mock_embedding,
        mock_graph_store,
        fast_timeout_config,
    ) -> None:
        from myrm_agent_harness.toolkits.memory.protocols.vector import (
            VectorDocument,
            VectorSearchResult,
        )

        mock_embedding.embed.return_value = [0.1] * 768
        mock_vector_store.count.return_value = 1
        mock_vector_store.search.return_value = [
            VectorSearchResult(
                document=VectorDocument(
                    id="evt-1",
                    content="Shipped canary rollout.",
                    vector=[0.1] * 768,
                    metadata={
                        "memory_type": "episodic",
                        "event_type": "user_action",
                        "importance": 0.5,
                        "confidence": 1.0,
                        "access_count": 0,
                        "namespaces": ["global"],
                        "primary_namespace": "global",
                    },
                ),
                score=0.9,
            )
        ]
        mock_graph_store.find_nodes.side_effect = _hang_forever

        manager = MemoryManager(
            fast_timeout_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            graph=mock_graph_store,
            auto_warmup=False,
        )

        results = await manager.search(
            "deploy policy",
            memory_types=[MemoryType.CLAIM, MemoryType.EPISODIC],
            limit=10,
            use_rrf=False,
        )

        assert manager.last_retrieval_trace is not None
        assert manager.last_retrieval_trace.degraded is True
        graph_step = next(step for step in manager.last_retrieval_trace.steps if step.phase == "graph")
        assert graph_step.status == "warning"
        assert len(results) >= 1  # collected candidates survive the graph skip


class TestCollectErrorDegradation:
    """A store task raising mid-collect must degrade recall instead of raising."""

    @pytest.mark.asyncio
    async def test_store_error_marks_degraded(self, mock_vector_store, mock_embedding, fast_timeout_config) -> None:
        metrics = get_search_metrics()
        before_error = metrics.snapshot().degradation_error_count

        mock_embedding.embed.return_value = [0.1] * 768
        mock_vector_store.count.return_value = 1
        mock_vector_store.search.side_effect = RuntimeError("vector backend unavailable")

        manager = MemoryManager(
            fast_timeout_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            auto_warmup=False,
        )

        results = await manager.search("weather", memory_types=[MemoryType.SEMANTIC], limit=10, use_rrf=False)

        assert results == []
        assert manager.last_retrieval_trace is not None
        assert manager.last_retrieval_trace.degraded is True
        assert metrics.snapshot().degradation_error_count == before_error + 1


class TestMemorySaveManageBranches:
    """Boundary guards of memory_save_tool / memory_manage_tool.

    Covers unknown-category/action guards and store-availability notices that
    would otherwise leave the agent surface partially untested.
    """

    @staticmethod
    def _tools(fast_timeout_config: MemoryConfig) -> list[object]:
        from myrm_agent_harness.toolkits.memory.agent_surface.memory_agent_tools import (
            create_memory_tools,
        )

        manager = MemoryManager(
            fast_timeout_config,
            user_id="test_user",
            auto_warmup=False,
        )
        return create_memory_tools(manager)

    @staticmethod
    def _find(tools: list[object], name: str) -> object:
        return next(t for t in tools if getattr(t, "name", None) == name)

    @pytest.mark.asyncio
    async def test_save_unknown_category(self, fast_timeout_config) -> None:
        save = self._find(self._tools(fast_timeout_config), "memory_save_tool")

        text = await save.coroutine(content="x", category="bogus")

        assert text == "Unknown category: bogus"

    @pytest.mark.asyncio
    async def test_manage_unknown_category_and_action(self, fast_timeout_config) -> None:
        manage = self._find(self._tools(fast_timeout_config), "memory_manage_tool")

        assert await manage.coroutine(action="update", memory_id="m1", category="bogus") == "Unknown category: bogus"
        assert await manage.coroutine(action="bogus", memory_id="m1", category="knowledge") == "Unknown action: bogus"

    @pytest.mark.asyncio
    async def test_save_not_enabled_guards(self, fast_timeout_config) -> None:
        save = self._find(self._tools(fast_timeout_config), "memory_save_tool")

        assert "Profile memory is not enabled." in (
            await save.coroutine(content="x", category="preference", preference_key="k")
        )
        assert "Procedural memory is not enabled." in (await save.coroutine(content="x", category="instruction"))

    @pytest.mark.asyncio
    async def test_manage_not_enabled_guards(self, fast_timeout_config) -> None:
        manage = self._find(self._tools(fast_timeout_config), "memory_manage_tool")

        assert "knowledge memory is not enabled." in (
            await manage.coroutine(action="delete", memory_id="m1", category="knowledge")
        )
        assert "Procedural memory is not enabled." in (
            await manage.coroutine(action="delete", memory_id="m1", category="rule")
        )
        assert "Knowledge memory is not enabled." in (
            await manage.coroutine(
                action="correct",
                memory_id="m1",
                category="knowledge",
                new_content="c",
            )
        )
