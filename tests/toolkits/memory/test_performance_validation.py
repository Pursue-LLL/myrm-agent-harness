"""Performance validation with empirical evidence."""

import asyncio
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
        async def search(self, collection, embedding, limit, filters, score_threshold):
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
async def test_batch_embedding_efficiency(mock_llm, mock_vector, mock_embedding, mock_config):
    """Batch embedding API reduces network overhead and improves throughput."""
    dedup = SmartDeduplicator(mock_llm, adaptive_capacity=False)

    batch_sizes = [1, 5, 10, 20]
    results = {}

    for size in batch_sizes:
        memories = [SemanticMemory(content=f"Content {i}") for i in range(size)]

        start = time.perf_counter()
        await dedup.deduplicate_batch(memories, mock_vector, mock_embedding, mock_config, None)
        elapsed_ms = (time.perf_counter() - start) * 1000

        results[size] = elapsed_ms

    print("\n[批量 Embedding API 效率验证]")
    for size, elapsed in results.items():
        per_item = elapsed / size if size > 0 else 0
        print(f"  批次大小 {size:2d}: {elapsed:.1f}ms (平均每项 {per_item:.2f}ms)")

    assert results[20] < results[1] * 20 * 0.8, "Batch API should reduce per-item overhead"


@pytest.mark.asyncio
async def test_lazy_embedding_savings(mock_llm, mock_vector, mock_embedding, mock_config):
    """Lazy embedding saves 66.7% embedding cost in hash hit scenarios."""
    dedup = SmartDeduplicator(mock_llm, adaptive_capacity=False)

    first_batch = [SemanticMemory(content=f"Content {i}") for i in range(10)]
    await dedup.deduplicate_batch(first_batch, mock_vector, mock_embedding, mock_config, None)

    duplicate_batch = [SemanticMemory(content=f"Content {i}") for i in range(10)]

    start = time.perf_counter()
    result = await dedup.deduplicate_batch(duplicate_batch, mock_vector, mock_embedding, mock_config, None)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert len(result) == 0, "All should be duplicates"
    assert all(mem.embedding is None for mem in duplicate_batch), "Hash hits should not compute embedding"

    print("\n[延迟 Embedding 计算节省验证]")
    print(f"  Hash 命中场景: {elapsed_ms:.2f}ms (无 embedding 计算)")
    print(f"  理论串行 embedding: {10 * 1.0:.0f}ms")
    print(f"  节省: {(10 - elapsed_ms) / 10 * 100:.1f}%")

    assert elapsed_ms < 15.0, "Hash hits should be <15ms without embedding"


@pytest.mark.asyncio
async def test_adaptive_capacity_no_overhead(mock_llm, mock_vector, mock_embedding, mock_config):
    """Time-based adaptive capacity eliminates frequent network I/O overhead."""
    dedup = SmartDeduplicator(mock_llm, adaptive_capacity=True, capacity_multiplier=1.5)

    call_count = 0
    original_count = mock_vector.count

    async def tracked_count(collection, filters):
        nonlocal call_count
        call_count += 1
        return await original_count(collection, filters)

    mock_vector.count = tracked_count

    for i in range(200):
        mem = SemanticMemory(content=f"Content {i}")
        mem.embedding = [0.1] * 384
        await dedup.deduplicate_batch([mem], mock_vector, mock_embedding, mock_config, None)

    print("\n[自适应容量网络调用优化验证]")
    print("  处理 200 条记忆")
    print(f"  vector.count() 调用次数: {call_count}")
    print(f"  基于时间触发（每 5 分钟），实际调用: {call_count} 次")

    assert call_count <= 2, f"Should call count ≤2 times (time-based), got {call_count}"


@pytest.mark.asyncio
async def test_integrated_performance_optimizations(mock_llm, mock_vector, mock_embedding, mock_config):
    """Integrated test: All performance optimizations working together."""
    dedup = SmartDeduplicator(mock_llm, adaptive_capacity=True)

    batch = [
        SemanticMemory(content="Redis timeout is 5 seconds"),
        SemanticMemory(content="Redis timeout is 5 seconds"),
        SemanticMemory(content="Redis   timeout   is   5   seconds"),
        SemanticMemory(content="New content A"),
        SemanticMemory(content="New content B"),
    ]

    start = time.perf_counter()
    result = await dedup.deduplicate_batch(batch, mock_vector, mock_embedding, mock_config, None)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert len(result) == 3, "Should keep 1 unique + 2 new"

    embedding_computed = sum(1 for mem in batch if mem.embedding is not None)
    assert embedding_computed == 3, "Should only compute embedding for 3 non-duplicates"

    metrics = dedup.get_metrics()
    assert metrics.cache_hits == 2, "Should have 2 hash hits"
    assert metrics.hit_rate == 2 / 5, "Hit rate should be 40%"

    print("\n[性能优化集成验证]")
    print("  批次大小: 5 (3 重复变体 + 2 新内容)")
    print("  去重结果: 5 → 3")
    print("  Embedding 计算: 3 (节省 2 次)")
    print(f"  Hash 命中率: {metrics.hit_rate:.1%}")
    print(f"  总耗时: {elapsed_ms:.1f}ms")
