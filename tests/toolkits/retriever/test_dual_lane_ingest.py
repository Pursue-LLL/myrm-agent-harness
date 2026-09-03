"""Unit and integration tests for Dual-Lane Ingest Pipeline with bounded backpressure.

Tests cover:
1. DirTreeBuilder ancestor parsing and bottom-up DAG reduce order.
2. BatchEmbedConsumer batching, idle flush timeout, and vector upsert.
3. DualLaneIngestPipeline concurrent Object/Job lane execution with bounded backpressure.
4. Single-file failure isolation (error resilience).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest

from myrm_agent_harness.toolkits.retriever.ingest.consumer import BatchEmbedConsumer
from myrm_agent_harness.toolkits.retriever.ingest.pipeline import DualLaneIngestPipeline
from myrm_agent_harness.toolkits.retriever.ingest.tree import (
    DirTreeBuilder,
    ancestor_dirs,
    dir_depth,
)
from myrm_agent_harness.toolkits.retriever.ingest.types import (
    Chunk,
    IngestStats,
    TaskEnvelope,
)
from myrm_agent_harness.toolkits.vector.base import FilterDict, SearchResult, VectorDocument


class MockEmbedder:
    def __init__(self, dimension: int = 128) -> None:
        self.dimension = dimension
        self.embed_calls: list[list[str]] = []

    async def embed(self, text: str) -> list[float]:
        return [0.1] * self.dimension

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls.append(texts)
        return [[0.1] * self.dimension for _ in texts]


class MockVectorStore:
    def __init__(self) -> None:
        self.upserted_docs: list[VectorDocument] = []

    async def upsert(self, collection: str, documents: Sequence[VectorDocument]) -> list[str]:
        self.upserted_docs.extend(documents)
        return [doc.id for doc in documents]

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        *,
        limit: int = 10,
        filters: FilterDict | None = None,
        score_threshold: float | None = None,
    ) -> list[SearchResult]:
        return []

    async def get(self, collection: str, ids: list[str]) -> list[VectorDocument]:
        return [d for d in self.upserted_docs if d.id in ids]

    async def delete(self, collection: str, ids: list[str]) -> None:
        self.upserted_docs = [d for d in self.upserted_docs if d.id not in ids]


def test_ancestor_dirs_and_depth() -> None:
    assert ancestor_dirs("src/components/button.tsx") == ["/", "/src", "/src/components"]
    assert dir_depth("/") == 0
    assert dir_depth("/src") == 1
    assert dir_depth("/src/components") == 2


def test_dirtree_builder_bottom_up() -> None:
    builder = DirTreeBuilder()
    builder.add_object("src/components/button.tsx")
    builder.add_object("src/utils/math.ts")
    builder.add_object("README.md")

    initial_ready = builder.finalize()
    # Deepest directories should be ready first
    assert "/src/components" in initial_ready
    assert "/src/utils" in initial_ready
    assert "/" not in initial_ready  # '/' depends on '/src'
    assert "/src" not in initial_ready  # '/src' depends on subdirs

    # Summarize one child directory
    p1 = builder.on_directory_summarized("/src/components", "UI button components")
    assert p1 is None  # '/src' still waits for '/src/utils'

    p2 = builder.on_directory_summarized("/src/utils", "Math utilities")
    assert p2 == "/src"  # Now '/src' is ready!

    p3 = builder.on_directory_summarized("/src", "Core src module")
    assert p3 == "/"  # Now root '/' is ready!


@pytest.mark.asyncio
async def test_batch_embed_consumer_batching() -> None:
    queue: asyncio.Queue[TaskEnvelope | None] = asyncio.Queue()
    embedder = MockEmbedder()
    store = MockVectorStore()
    stats = IngestStats()

    consumer = BatchEmbedConsumer(
        queue=queue,
        embedder=embedder,
        vector_store=store,
        collection_name="test_col",
        batch_size=3,
        idle_flush_timeout_seconds=0.2,
        stats=stats,
    )
    consumer_task = asyncio.create_task(consumer.run())

    # Send 5 chunks
    for i in range(5):
        chunk = Chunk(content=f"Hello chunk {i}", uri=f"file_{i}.txt", chunk_index=0)
        await queue.put(TaskEnvelope(task_id=f"t_{i}", payload=chunk))

    await queue.put(None)  # Poison pill
    await consumer_task

    assert len(store.upserted_docs) == 5
    assert stats.total_chunks_embedded == 5
    # First batch of 3, second batch of 2 on flush
    assert len(embedder.embed_calls) == 2
    assert len(embedder.embed_calls[0]) == 3
    assert len(embedder.embed_calls[1]) == 2


@pytest.mark.asyncio
async def test_dual_lane_ingest_pipeline_end_to_end() -> None:
    embedder = MockEmbedder()
    store = MockVectorStore()

    pipeline = DualLaneIngestPipeline(
        embedder=embedder,
        vector_store=store,
        collection_name="test_e2e_col",
        max_queue_size=10,
        batch_size=4,
        max_parallel_workers=2,
    )

    object_uris = [
        "src/api/user.py",
        "src/api/auth.py",
        "src/models/user.py",
        "docs/overview.md",
    ]

    async def mock_producer(uri: str) -> list[Chunk]:
        return [
            Chunk(content=f"Code content of {uri} part 1", uri=uri, chunk_index=0),
            Chunk(content=f"Code content of {uri} part 2", uri=uri, chunk_index=1),
        ]

    async def mock_summarizer(dir_path: str, files: list[str], child_summaries: list[str]) -> str:
        return f"Summary of {dir_path} containing {len(files)} files"

    stats = await pipeline.run(
        object_uris=object_uris,
        object_producer=mock_producer,
        dir_summarizer=mock_summarizer,
    )

    assert stats.total_objects == 4
    assert stats.succeeded_objects == 4
    assert stats.failed_objects == 0
    # 4 objects * 2 chunks = 8 chunks
    assert stats.total_chunks_produced == 8
    # 8 object chunks + directories summarized
    assert len(store.upserted_docs) == 8 + stats.total_directories_summarized
    assert stats.total_directories_summarized >= 4


@pytest.mark.asyncio
async def test_dual_lane_ingest_fault_isolation() -> None:
    embedder = MockEmbedder()
    store = MockVectorStore()

    pipeline = DualLaneIngestPipeline(
        embedder=embedder,
        vector_store=store,
        collection_name="test_fault_col",
        max_queue_size=10,
        batch_size=2,
    )

    object_uris = ["valid_1.txt", "broken.txt", "valid_2.txt"]

    async def mock_producer(uri: str) -> list[Chunk]:
        if "broken" in uri:
            raise ValueError("Corrupted file encoding!")
        return [Chunk(content=f"Valid content of {uri}", uri=uri)]

    stats = await pipeline.run(object_uris=object_uris, object_producer=mock_producer)

    assert stats.total_objects == 3
    assert stats.succeeded_objects == 2
    assert stats.failed_objects == 1
    assert len(store.upserted_docs) == 2


@pytest.mark.asyncio
async def test_dual_lane_ingest_async_generator_producer_and_empty_list() -> None:
    embedder = MockEmbedder()
    store = MockVectorStore()

    pipeline = DualLaneIngestPipeline(
        embedder=embedder,
        vector_store=store,
        collection_name="test_async_gen_col",
        max_queue_size=5,
        batch_size=2,
    )

    # Test edge case 1: Empty object list
    stats_empty = await pipeline.run(object_uris=[], object_producer=lambda uri: [])
    assert stats_empty.total_objects == 0
    assert stats_empty.total_chunks_produced == 0

    # Test edge case 2: Async generator producer
    async def async_gen_producer(uri: str):
        for i in range(3):
            yield Chunk(content=f"Async stream chunk {i} from {uri}", uri=uri, chunk_index=i)

    stats_gen = await pipeline.run(
        object_uris=["stream_file.log"],
        object_producer=async_gen_producer,
    )
    assert stats_gen.total_objects == 1
    assert stats_gen.succeeded_objects == 1
    assert stats_gen.total_chunks_produced == 3
    assert len(store.upserted_docs) == 3
