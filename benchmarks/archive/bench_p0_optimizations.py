"""Comprehensive benchmark for P0 optimizations with real-world scenarios."""

import asyncio
import time

from myrm_agent_harness.toolkits.memory.strategies.deduplicator import SmartDeduplicator
from myrm_agent_harness.toolkits.memory.types import SemanticMemory


class MockLLM:
    """Mock LLM for benchmarking."""

    async def ainvoke(self, messages):
        class Response:
            content = "DECISION: NEW\nREASON: Test"

        return Response()


class MockVector:
    """Mock vector store."""

    def __init__(self):
        self.count_calls = 0

    async def search(self, collection, embedding, limit, filters, score_threshold):
        return []

    async def get(self, collection, ids):
        return []

    async def count(self, collection, filters):
        self.count_calls += 1
        return 500


class MockEmbedding:
    """Mock embedding with realistic latency."""

    @property
    def dimension(self):
        return 384

    async def embed(self, text):
        await asyncio.sleep(0.001)
        return [0.1] * 384

    async def embed_batch(self, texts):
        await asyncio.sleep(0.001 * len(texts))
        return [[0.1] * 384 for _ in texts]


class MockConfig:
    """Mock config."""

    semantic_collection = "test_semantic"
    episodic_collection = "test_episodic"

    class dedup:
        high_threshold = 0.95
        low_threshold = 0.60


async def benchmark_concurrent_embedding():
    """Benchmark P0.1: Concurrent embedding computation."""
    print("\n" + "=" * 80)
    print("P0.1 优化：并发 Embedding 计算")
    print("=" * 80)

    dedup = SmartDeduplicator(MockLLM(), adaptive_capacity=False)
    vector = MockVector()
    embedding = MockEmbedding()
    config = MockConfig()

    batch_sizes = [1, 5, 10, 20, 50]

    print(f"\n{'批次大小':<10} {'实际耗时':<15} {'理论串行':<15} {'加速比':<10} {'延迟降低'}")
    print("-" * 80)

    for size in batch_sizes:
        memories = [SemanticMemory(user_id="u1", content=f"Content {i}") for i in range(size)]

        start = time.perf_counter()
        await dedup.deduplicate_batch(memories, "u1", vector, embedding, config, None)
        elapsed_ms = (time.perf_counter() - start) * 1000

        expected_serial = size * 1.0
        speedup = expected_serial / elapsed_ms if elapsed_ms > 0 else 0
        reduction = (1 - elapsed_ms / expected_serial) * 100 if expected_serial > 0 else 0

        print(f"{size:<10} {elapsed_ms:>10.2f} ms {expected_serial:>10.0f} ms {speedup:>8.1f}x {reduction:>9.1f}%")


async def benchmark_lazy_embedding():
    """Benchmark P0.3: Lazy embedding computation."""
    print("\n" + "=" * 80)
    print("P0.3 优化：延迟 Embedding 计算")
    print("=" * 80)

    dedup = SmartDeduplicator(MockLLM(), adaptive_capacity=False)
    vector = MockVector()
    embedding = MockEmbedding()
    config = MockConfig()

    first_batch = [SemanticMemory(user_id="u1", content=f"Content {i}") for i in range(20)]
    await dedup.deduplicate_batch(first_batch, "u1", vector, embedding, config, None)

    duplicate_batch = [SemanticMemory(user_id="u1", content=f"Content {i}") for i in range(20)]

    start = time.perf_counter()
    result = await dedup.deduplicate_batch(duplicate_batch, "u1", vector, embedding, config, None)
    elapsed_ms = (time.perf_counter() - start) * 1000

    expected_with_embedding = 20 * 1.0
    savings = (1 - elapsed_ms / expected_with_embedding) * 100

    print("\n场景：20 条记忆全部命中 Hash 缓存")
    print(f"  实际耗时: {elapsed_ms:.2f} ms")
    print(f"  理论 embedding 成本: {expected_with_embedding:.0f} ms")
    print(f"  节省: {savings:.1f}%")
    print(f"  去重结果: {len(result)} 条（全部跳过）")
    print(f"  Embedding 计算: {sum(1 for m in duplicate_batch if m.embedding is not None)} 次（0 次）")


async def benchmark_adaptive_capacity():
    """Benchmark P0.2: Time-based adaptive capacity adjustment."""
    print("\n" + "=" * 80)
    print("P0.2 优化：时间触发容量调整")
    print("=" * 80)

    dedup = SmartDeduplicator(MockLLM(), adaptive_capacity=True, capacity_multiplier=1.5)
    vector = MockVector()
    embedding = MockEmbedding()
    config = MockConfig()

    print("\n场景：处理 200 条记忆（每条 1 个批次）")

    for i in range(200):
        mem = SemanticMemory(user_id="u1", content=f"Content {i}")
        mem.embedding = [0.1] * 384
        await dedup.deduplicate_batch([mem], "u1", vector, embedding, config, None)

    print(f"  vector.count() 调用次数: {vector.count_calls}")
    print("  优化前（每 100 次调用）: 4 次 (200/100 * 2 collections)")
    print(f"  优化后（每 5 分钟）: {vector.count_calls} 次")
    print(f"  网络调用减少: {(1 - vector.count_calls / 4) * 100:.1f}%")


async def benchmark_integrated():
    """Benchmark: All P0 optimizations working together."""
    print("\n" + "=" * 80)
    print("集成基准：P0 优化协同工作")
    print("=" * 80)

    dedup = SmartDeduplicator(MockLLM(), adaptive_capacity=True)
    vector = MockVector()
    embedding = MockEmbedding()
    config = MockConfig()

    batch = [
        SemanticMemory(user_id="u1", content="Redis timeout is 5 seconds"),
        SemanticMemory(user_id="u1", content="Redis timeout is 5 seconds"),
        SemanticMemory(user_id="u1", content="Redis   timeout   is   5   seconds"),
        SemanticMemory(user_id="u1", content="REDIS TIMEOUT IS 5 SECONDS"),
        SemanticMemory(user_id="u1", content="New content A"),
        SemanticMemory(user_id="u1", content="New content B"),
        SemanticMemory(user_id="u1", content="New content C"),
        SemanticMemory(user_id="u1", content="New content D"),
        SemanticMemory(user_id="u1", content="New content E"),
        SemanticMemory(user_id="u1", content="New content F"),
    ]

    start = time.perf_counter()
    result = await dedup.deduplicate_batch(batch, "u1", vector, embedding, config, None)
    elapsed_ms = (time.perf_counter() - start) * 1000

    embedding_computed = sum(1 for mem in batch if mem.embedding is not None)
    metrics = dedup.get_metrics()

    print("\n场景：10 条记忆（4 条重复变体 + 6 条新内容）")
    print("  批次大小: 10")
    print(f"  去重结果: 10 → {len(result)}")
    print(f"  Embedding 计算: {embedding_computed} 次（节省 {10 - embedding_computed} 次）")
    print(f"  Hash 命中率: {metrics.hit_rate:.1%}")
    print(f"  总耗时: {elapsed_ms:.2f} ms")
    print(f"  平均每条: {elapsed_ms / 10:.2f} ms")


async def main():
    """Run all benchmarks."""
    print("\n" + "=" * 80)
    print("Memory Deduplication P0 优化性能基准测试")
    print("=" * 80)

    await benchmark_concurrent_embedding()
    await benchmark_lazy_embedding()
    await benchmark_adaptive_capacity()
    await benchmark_integrated()

    print("\n" + "=" * 80)
    print("基准测试完成")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
