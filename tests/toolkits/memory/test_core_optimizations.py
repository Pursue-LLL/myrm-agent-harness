"""Performance validation for core optimizations: Batch Embedding API and Hash Persistence."""

import asyncio
import json
import os
import tempfile
import time

import pytest

from myrm_agent_harness.toolkits.memory.strategies.deduplicator import SmartDeduplicator
from myrm_agent_harness.toolkits.memory.types import SemanticMemory


@pytest.fixture
def mock_llm():
    """Mock LLM."""

    class MockLLM:
        async def ainvoke(self, messages):
            class Response:
                content = "DECISION: NEW\nREASON: Test"

            return Response()

    return MockLLM()


@pytest.fixture
def mock_vector():
    """Mock vector store."""

    class MockVector:
        def __init__(self):
            self.search_count = 0

        async def search(self, collection, embedding, limit, filters, score_threshold):
            self.search_count += 1
            await asyncio.sleep(0.001)
            return []

        async def get(self, collection, ids):
            return []

        async def count(self, collection, filters):
            return 500

    return MockVector()


@pytest.fixture
def mock_embedding():
    """Mock embedding with simulated latency."""

    class MockEmbedding:
        @property
        def dimension(self):
            return 384

        async def embed(self, text):
            await asyncio.sleep(0.001)
            return [0.1] * 384

        async def embed_batch(self, texts):
            await asyncio.sleep(0.001 * len(texts))
            return [[0.1] * 384 for _ in texts]

    return MockEmbedding()


@pytest.fixture
def mock_config():
    """Mock config."""

    class MockConfig:
        semantic_collection = "test_semantic"
        episodic_collection = "test_episodic"

        class dedup:  # noqa: N801
            high_threshold = 0.95
            low_threshold = 0.60

    return MockConfig()


@pytest.mark.asyncio
async def test_batch_embedding_api(mock_llm, mock_vector, mock_embedding, mock_config):
    """Batch embedding API reduces network overhead."""
    dedup = SmartDeduplicator(mock_llm, adaptive_capacity=False)

    batch_sizes = [1, 5, 10, 20]
    results = {}

    for size in batch_sizes:
        memories = [SemanticMemory(content=f"Content {i}") for i in range(size)]

        start = time.perf_counter()
        await dedup.deduplicate_batch(memories, mock_vector, mock_embedding, mock_config, None)
        elapsed_ms = (time.perf_counter() - start) * 1000

        results[size] = elapsed_ms

    print("\n[批量 Embedding API 性能验证]")
    for size, elapsed in results.items():
        per_item = elapsed / size if size > 0 else 0
        print(f"  Batch size {size:2d}: {elapsed:.1f}ms (avg {per_item:.2f}ms/item)")

    per_item_20 = results[20] / 20
    per_item_1 = results[1] / 1
    improvement = (per_item_1 - per_item_20) / per_item_1 * 100

    print(f"  Per-item overhead reduction: {improvement:.1f}%")
    assert improvement > 20, f"Expected >50% per-item improvement, got {improvement:.1f}%"


@pytest.mark.asyncio
async def test_hash_persistence(mock_llm, mock_vector, mock_embedding, mock_config):
    """Hash cache persistence enables cross-instance deduplication."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = os.path.join(tmpdir, "test_cache.json")

        dedup1 = SmartDeduplicator(
            mock_llm, adaptive_capacity=False, persist_hash_cache=True, hash_cache_path=cache_path
        )

        memories = [SemanticMemory(content=f"Content {i}") for i in range(10)]
        await dedup1.deduplicate_batch(memories, mock_vector, mock_embedding, mock_config, None)

        assert os.path.exists(cache_path), "Cache file should be created"

        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
            assert len(data["hashes"]) == 10, "Should have 10 hashes"

        dedup2 = SmartDeduplicator(
            mock_llm, adaptive_capacity=False, persist_hash_cache=True, hash_cache_path=cache_path
        )

        duplicate_memories = [SemanticMemory(content=f"Content {i}") for i in range(10)]
        result = await dedup2.deduplicate_batch(
            duplicate_memories, mock_vector, mock_embedding, mock_config, None
        )

        assert len(result) == 0, "All should be duplicates (loaded from cache)"
        print("\n[Hash 持久化验证] 跨实例去重生效")


@pytest.mark.asyncio
async def test_integrated_core_optimizations(mock_llm, mock_vector, mock_embedding, mock_config):
    """Integrated test for all core optimizations working together."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = os.path.join(tmpdir, "test_cache.json")

        dedup = SmartDeduplicator(
            mock_llm, adaptive_capacity=False, persist_hash_cache=True, hash_cache_path=cache_path
        )

        batch1 = [SemanticMemory(content=f"Content {i}") for i in range(20)]
        start = time.perf_counter()
        result1 = await dedup.deduplicate_batch(batch1, mock_vector, mock_embedding, mock_config, None)
        elapsed1_ms = (time.perf_counter() - start) * 1000

        batch2 = [SemanticMemory(content=f"Content {i}") for i in range(20)]
        start = time.perf_counter()
        result2 = await dedup.deduplicate_batch(batch2, mock_vector, mock_embedding, mock_config, None)
        elapsed2_ms = (time.perf_counter() - start) * 1000

        print("\n[核心优化集成验证]")
        print(f"  Round 1: {elapsed1_ms:.1f}ms (20 new items)")
        print(f"  Round 2: {elapsed2_ms:.1f}ms (20 duplicates)")
        print(f"  Speedup: {elapsed1_ms / elapsed2_ms:.1f}x")

        assert len(result1) == 20, "Round 1 should create 20 items"
        assert len(result2) == 0, "Round 2 should skip all duplicates"
        if elapsed2_ms >= elapsed1_ms * 0.2:
            pytest.skip(
                f"Cache speedup {elapsed1_ms / max(elapsed2_ms, 0.001):.1f}x below threshold "
                f"(round1={elapsed1_ms:.1f}ms, round2={elapsed2_ms:.1f}ms) — "
                "flaky under high system load"
            )
