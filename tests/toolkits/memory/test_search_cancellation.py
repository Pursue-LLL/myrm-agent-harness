# [POS] myrm-agent-harness/tests/toolkits/memory/test_search_cancellation.py
# [INPUT] myrm_agent_harness.toolkits.memory.manager::MemoryManager, utils.runtime.cancellation::reraise_if_cancelled
# [OUTPUT] Regression gate: a stop aimed at the search task reaches the caller; benign failures keep degrading

"""A stop aimed at a memory search must reach the caller, not be reported as a degraded result.

Retrieval intentionally fails open: a hanging store or a provider error degrades recall instead of
blocking the turn. `except BaseException` in the embed and graph stages made that fail-open behavior
swallow a genuine stop too, so a user pressing Stop (or a tool-level timeout firing) was turned into a
plain "degraded" success and the turn kept running on a task nobody was waiting for. These tests pin
the boundary: a stop aimed at the search task propagates, every other failure still degrades, and a
stopped collect leaves no store task holding its handles.
"""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.toolkits.memory.config import MemoryConfig, RetrievalConfig
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import MemoryType

_TIMEOUT_CONFIG = 30.0


def _fast_config() -> MemoryConfig:
    """Config whose retrieval budget is far longer than the test's own patience."""
    return MemoryConfig(
        embedding_model="test-model",
        collection_prefix="test_memory",
        retrieval=RetrievalConfig(timeout_seconds=_TIMEOUT_CONFIG),
    )


def _live_tasks(exclude: set[asyncio.Task[object]]) -> list[asyncio.Task[object]]:
    """Every unfinished task that appeared after ``exclude`` was captured."""
    current = asyncio.current_task()
    return [t for t in asyncio.all_tasks() if t not in exclude and t is not current and not t.done()]


@pytest.fixture
async def _no_background_tasks():
    """Snapshot the task set so a test can prove nothing it started outlives it."""
    yield set(asyncio.all_tasks())


class TestStopPropagatesThroughFailOpenStages:
    """A stop must not be converted into the degraded result those stages use for real failures."""

    @pytest.mark.asyncio
    async def test_stop_during_embedding_reaches_the_caller(self, mock_vector_store, mock_embedding) -> None:
        """A stop while the query embedding is in flight is the caller's, not a degrade-worthy error."""
        embedding_started = asyncio.Event()

        async def _hang_embed(*args: object, **kwargs: object) -> list[float]:
            embedding_started.set()
            await asyncio.sleep(600)
            return [0.1] * 768

        mock_embedding.embed.side_effect = _hang_embed
        mock_vector_store.count.return_value = 1
        mock_vector_store.search.return_value = []

        manager = MemoryManager(
            _fast_config(),
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            auto_warmup=False,
        )

        search = asyncio.create_task(manager.search("q", memory_types=[MemoryType.SEMANTIC], limit=5, use_rrf=False))
        await asyncio.wait_for(embedding_started.wait(), timeout=5.0)
        search.cancel()

        with pytest.raises(asyncio.CancelledError):
            await search

    @pytest.mark.asyncio
    async def test_stop_during_graph_enrichment_reaches_the_caller(
        self, mock_vector_store, mock_embedding, mock_graph_store
    ) -> None:
        """The graph stage swallows real failures too, so it needs the same stop boundary."""
        from myrm_agent_harness.toolkits.memory.protocols.vector import (
            VectorDocument,
            VectorSearchResult,
        )

        graph_started = asyncio.Event()

        async def _hang_graph(*args: object, **kwargs: object) -> list[object]:
            graph_started.set()
            await asyncio.sleep(600)
            return []

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
        mock_graph_store.find_nodes.side_effect = _hang_graph

        manager = MemoryManager(
            _fast_config(),
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            graph=mock_graph_store,
            auto_warmup=False,
        )

        search = asyncio.create_task(
            manager.search("deploy policy", memory_types=[MemoryType.CLAIM], limit=5, use_rrf=False)
        )
        await asyncio.wait_for(graph_started.wait(), timeout=5.0)
        search.cancel()

        with pytest.raises(asyncio.CancelledError):
            await search


class TestBenignFailuresStillDegrade:
    """The fail-open contract is the point of these handlers; only a real stop may escape them."""

    @pytest.mark.asyncio
    async def test_store_error_still_returns_degraded_results(
        self, mock_vector_store, mock_embedding, _no_background_tasks
    ) -> None:
        """A store that raises keeps its degraded-not-raised behaviour after the stop fix."""
        mock_embedding.embed.return_value = [0.1] * 768
        mock_vector_store.count.return_value = 1
        mock_vector_store.search.side_effect = RuntimeError("vector backend unavailable")

        manager = MemoryManager(
            _fast_config(),
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            auto_warmup=False,
        )

        results = await manager.search("weather", memory_types=[MemoryType.SEMANTIC], limit=5, use_rrf=False)

        assert results == []
        assert manager.last_retrieval_trace is not None
        assert manager.last_retrieval_trace.degraded is True

    @pytest.mark.asyncio
    async def test_embedding_error_still_fails_open(self, mock_vector_store, mock_embedding) -> None:
        """An embedding provider error must still degrade to local-only recall, never raise."""
        mock_embedding.embed.side_effect = RuntimeError("provider 500")
        mock_vector_store.count.return_value = 1
        mock_vector_store.search.return_value = []

        manager = MemoryManager(
            _fast_config(),
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            auto_warmup=False,
        )

        results = await manager.search("weather", memory_types=[MemoryType.SEMANTIC], limit=5, use_rrf=False)

        assert results == []
        trace = manager.last_retrieval_trace
        assert trace is not None
        assert trace.degraded is True
        assert next(step for step in trace.steps if step.phase == "embed").status == "warning"


class TestStoppedCollectLeavesNoStoreTasks:
    """`asyncio.wait` does not cancel what it awaits, so a stopped collect must clean up itself."""

    @pytest.mark.asyncio
    async def test_no_store_task_survives_a_stop(self, mock_relational_store, _no_background_tasks) -> None:
        """A store search still running when the turn stops must not keep holding its handles."""
        store_started = asyncio.Event()

        async def _hang_rules(*args: object, **kwargs: object) -> list[object]:
            store_started.set()
            await asyncio.sleep(600)
            return []

        mock_relational_store.search_rules.side_effect = _hang_rules

        manager = MemoryManager(
            _fast_config(),
            user_id="test_user",
            relational=mock_relational_store,
            auto_warmup=False,
        )
        manager._search_service._fts5_searcher = None

        search = asyncio.create_task(manager.search("q", memory_types=[MemoryType.PROCEDURAL], limit=5, use_rrf=False))
        await asyncio.wait_for(store_started.wait(), timeout=5.0)
        search.cancel()

        with pytest.raises(asyncio.CancelledError):
            await search

        # Give the cancelled children a chance to unwind before counting survivors.
        await asyncio.sleep(0.05)
        assert not _live_tasks(_no_background_tasks), "a store task outlived the stopped search"
