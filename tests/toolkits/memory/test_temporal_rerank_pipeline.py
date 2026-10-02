"""Pipeline integration tests: temporal window derivation + cross-encoder rerank.

End-to-end through ``MemoryManager.search`` with mocked backends: the
derived temporal window lands on the route trace metadata, explicit bounds
win over derivation (explicit-scope invariance), and the rerank gate
reorders the fused head while recording its trace step.
"""

from datetime import UTC, datetime

import pytest

from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument
from myrm_agent_harness.toolkits.memory.protocols.vector import (
    VectorSearchResult as VectorSearchHit,
)
from myrm_agent_harness.toolkits.memory.types import MemoryType
from myrm_agent_harness.toolkits.retriever.reranker.base import RerankerService, RerankResult


class StubReranker(RerankerService):
    """Scripted reranker handing out fixed pair scores. No network."""

    def __init__(self, scores: list[float]) -> None:
        self.scores = scores

    async def rerank(self, query: str, documents: list[str], top_k: int | None = None) -> list[RerankResult]:
        raise AssertionError("gate must call rerank_pairs, not rerank")

    async def rerank_pairs(self, pairs: list[tuple[str, str]]) -> list[float]:
        return list(self.scores)


def _doc(doc_id: str, content: str) -> VectorDocument:
    """Vector doc in the BM25-test shape: semantic defaults, fresh timestamps."""
    now = datetime.now(UTC)
    return VectorDocument(
        id=doc_id,
        content=content,
        vector=[0.1] * 768,
        metadata={
            "memory_type": "semantic",
            "importance": 0.5,
            "confidence": 1.0,
            "source_chat_id": "",
            "preference_type": "",
            "preference_strength": 0.0,
            "correction_of": "",
            "access_count": 0,
        },
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def memory_config() -> MemoryConfig:
    return MemoryConfig(embedding_model="test-model")


@pytest.fixture
def seeded_vector_store(mock_vector_store):
    """Vector search returns four semantic hits in descending fused order.

    Scroll stays cold (empty) so the BM25 mirror adds no second channel: the
    fused order equals the hit order, keeping rerank assertions deterministic.
    """
    docs = [
        _doc("doc-a", "部署方案的容量评估"),
        _doc("doc-b", "数据库分片迁移记录"),
        _doc("doc-c", "上周的服务告警复盘"),
        _doc("doc-d", "网关限流参数的调整"),
    ]
    mock_vector_store.scroll.return_value = ([], None)
    mock_vector_store.search.return_value = [
        VectorSearchHit(document=doc, score=score)
        for doc, score in zip(docs, (0.9, 0.8, 0.7, 0.6), strict=True)
    ]
    return mock_vector_store


def _route_step(trace):
    return next(step for step in trace.steps if step.phase == "route")


def _rerank_step(trace):
    return next(step for step in trace.steps if step.phase == "rerank")


async def test_derived_temporal_window_lands_on_route_trace(
    memory_config, seeded_vector_store, mock_embedding
) -> None:
    manager = MemoryManager(
        memory_config,
        user_id="user",
        vector=seeded_vector_store,
        embedding=mock_embedding,
    )
    await manager.search("昨天讨论的部署方案", memory_types=[MemoryType.SEMANTIC])

    trace = manager.last_retrieval_trace
    assert trace is not None
    window = _route_step(trace).metadata["temporal_window"]
    assert window is not None
    assert window["marker"] == "昨天"
    assert window["kind"] == "day"
    assert window["since"] and window["until"]


async def test_explicit_bounds_win_over_derivation(
    memory_config, seeded_vector_store, mock_embedding
) -> None:
    manager = MemoryManager(
        memory_config,
        user_id="user",
        vector=seeded_vector_store,
        embedding=mock_embedding,
    )
    explicit_since = datetime(2026, 9, 1, tzinfo=UTC)
    await manager.search(
        "昨天讨论的部署方案",
        memory_types=[MemoryType.SEMANTIC],
        since=explicit_since,
    )

    trace = manager.last_retrieval_trace
    assert trace is not None
    # An explicit bound is honored untouched: no derived window in the trace.
    assert _route_step(trace).metadata["temporal_window"] is None


async def test_temporal_window_disabled_by_config(
    memory_config, seeded_vector_store, mock_embedding
) -> None:
    from dataclasses import replace

    config = replace(
        memory_config,
        retrieval=replace(memory_config.retrieval, enable_temporal_window=False),
    )
    manager = MemoryManager(
        config,
        user_id="user",
        vector=seeded_vector_store,
        embedding=mock_embedding,
    )
    await manager.search("昨天讨论的部署方案", memory_types=[MemoryType.SEMANTIC])

    trace = manager.last_retrieval_trace
    assert trace is not None
    assert _route_step(trace).metadata["temporal_window"] is None


async def test_rerank_gate_reorders_and_records_trace(
    memory_config, seeded_vector_store, mock_embedding
) -> None:
    # Cross-encoder prefers doc-b (index 1) over the fused order.
    reranker = StubReranker(scores=[0.2, 0.9, 0.5, 0.1])
    manager = MemoryManager(
        memory_config,
        user_id="user",
        vector=seeded_vector_store,
        embedding=mock_embedding,
        reranker=reranker,
    )
    results = await manager.search("数据库的迁移记录", memory_types=[MemoryType.SEMANTIC])

    assert next(result.memory.id for result in results) == "doc-b"

    trace = manager.last_retrieval_trace
    assert trace is not None
    step = _rerank_step(trace)
    assert step.status == "success"
    assert step.metadata["applied"] is True
    assert step.metadata["reranked_count"] == len(results)
    assert step.metadata["skip_reason"] is None


async def test_rerank_step_skipped_without_reranker(
    memory_config, seeded_vector_store, mock_embedding
) -> None:
    manager = MemoryManager(
        memory_config,
        user_id="user",
        vector=seeded_vector_store,
        embedding=mock_embedding,
    )
    await manager.search("数据库的迁移记录", memory_types=[MemoryType.SEMANTIC])

    trace = manager.last_retrieval_trace
    assert trace is not None
    step = _rerank_step(trace)
    assert step.status == "skipped"
    assert step.metadata["skip_reason"] == "no_reranker"
