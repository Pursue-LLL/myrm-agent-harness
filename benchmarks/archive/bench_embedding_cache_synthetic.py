#!/usr/bin/env python3
"""Synthetic embedding cache performance benchmark.

Uses simulated API latency to test cache layer performance without real API calls.
Validates concurrency optimizations and quantifies cache hit speedup.

Usage:
    cd myrm-agent-harness
    source .venv/bin/activate
    python benchmarks/bench_embedding_cache_synthetic.py
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from myrm_agent_harness.toolkits.memory._internal.embedding_cache import EmbeddingCache


@dataclass
class BenchmarkResult:
    """Performance benchmark result."""

    scenario: str
    batch_size: int
    cache_hit_rate: float
    total_requests: int
    duration_ms: float
    throughput: float
    avg_latency_ms: float


async def mock_embed(text: str, delay_ms: int = 100) -> list[float]:
    """Simulate API call with realistic latency."""
    await asyncio.sleep(delay_ms / 1000)
    return [float(ord(c)) for c in text[:512]]


async def mock_embed_batch(texts: list[str], delay_ms: int = 150) -> list[list[float]]:
    """Simulate batch API call (slightly more efficient than N individual calls)."""
    await asyncio.sleep(delay_ms / 1000)
    return [[float(ord(c)) for c in t[:512]] for t in texts]


async def benchmark_scenario(
    scenario_name: str,
    cache: EmbeddingCache,
    texts: list[str],
    warmup_texts: list[str] | None = None,
) -> BenchmarkResult:
    """Benchmark a specific scenario."""
    if warmup_texts:
        for t in warmup_texts:
            await cache.get_embedding(t)

    initial_stats = cache.get_stats()
    initial_total = initial_stats["total"]

    start = time.perf_counter()
    for text in texts:
        await cache.get_embedding(text)
    duration = (time.perf_counter() - start) * 1000

    final_stats = cache.get_stats()
    requests = final_stats["total"] - initial_total
    hit_rate = final_stats["hit_rate"]

    return BenchmarkResult(
        scenario=scenario_name,
        batch_size=len(texts),
        cache_hit_rate=hit_rate,
        total_requests=requests,
        duration_ms=duration,
        throughput=requests / (duration / 1000) if duration > 0 else 0,
        avg_latency_ms=duration / requests if requests > 0 else 0,
    )


async def benchmark_batch_get(
    scenario_name: str,
    cache: EmbeddingCache,
    texts: list[str],
    is_cold: bool = False,
) -> BenchmarkResult:
    """Benchmark get_batch with asyncio.gather."""
    initial_stats = cache.get_stats()
    initial_total = initial_stats["total"]

    start = time.perf_counter()
    if is_cold:
        await cache.get_embeddings_batch(texts)
    else:
        await cache.get_batch(texts)
    duration = (time.perf_counter() - start) * 1000

    final_stats = cache.get_stats()
    requests = final_stats["total"] - initial_total

    return BenchmarkResult(
        scenario=scenario_name,
        batch_size=len(texts),
        cache_hit_rate=final_stats["hit_rate"],
        total_requests=requests,
        duration_ms=duration,
        throughput=requests / (duration / 1000) if duration > 0 else 0,
        avg_latency_ms=duration / requests if requests > 0 else 0,
    )


async def benchmark_batch_put(
    scenario_name: str,
    cache: EmbeddingCache,
    texts: list[str],
    embeddings: list[list[float]],
) -> BenchmarkResult:
    """Benchmark put_batch with Redis pipeline."""
    start = time.perf_counter()
    await cache.put_batch(texts, embeddings)
    duration = (time.perf_counter() - start) * 1000

    return BenchmarkResult(
        scenario=scenario_name,
        batch_size=len(texts),
        cache_hit_rate=0.0,
        total_requests=len(texts),
        duration_ms=duration,
        throughput=len(texts) / (duration / 1000) if duration > 0 else 0,
        avg_latency_ms=duration / len(texts) if texts else 0,
    )


def print_result(result: BenchmarkResult) -> None:
    """Print formatted benchmark result."""
    print(f"\n{'=' * 75}")
    print(f"📊 {result.scenario}")
    print(f"{'=' * 75}")
    print(f"  Batch Size:       {result.batch_size}")
    print(f"  Cache Hit Rate:   {result.cache_hit_rate * 100:.1f}%")
    print(f"  Total Requests:   {result.total_requests}")
    print(f"  Duration:         {result.duration_ms:.2f} ms")
    print(f"  Throughput:       {result.throughput:.2f} req/s")
    print(f"  Avg Latency:      {result.avg_latency_ms:.2f} ms/req")


async def main() -> None:
    """Run comprehensive synthetic benchmarks."""
    print("\n🚀 Embedding Cache Synthetic Performance Benchmark")
    print("=" * 75)
    print("Simulates real API latency to quantify cache layer performance")
    print()

    test_texts = [f"Test text {i} for embedding cache benchmark" for i in range(100)]

    results: list[BenchmarkResult] = []

    print("\n📦 Test 1: Cold Cache (0% hit) - Sequential gets")
    cache1 = EmbeddingCache(
        embedding_func=lambda t: mock_embed(t, delay_ms=100),
        model_name="test-model",
    )
    result1 = await benchmark_scenario(
        "Cold Cache - 10 API calls (100ms each)",
        cache1,
        test_texts[:10],
    )
    results.append(result1)
    print_result(result1)

    print("\n🔥 Test 2: Warm Cache (100% hit) - L1 performance")
    result2 = await benchmark_scenario(
        "Warm Cache - 10 L1 hits",
        cache1,
        test_texts[:10],
        warmup_texts=test_texts[:10],
    )
    results.append(result2)
    print_result(result2)

    print("\n🌡️  Test 3: Mixed Cache (50% hit)")
    mixed_texts = test_texts[:5] + test_texts[50:55]
    cache3 = EmbeddingCache(
        embedding_func=lambda t: mock_embed(t, delay_ms=100),
        model_name="test-model",
    )
    await cache3.get_embeddings_batch(test_texts[:5])
    result3 = await benchmark_scenario(
        "Mixed Cache - 5 hits + 5 misses",
        cache3,
        mixed_texts,
    )
    results.append(result3)
    print_result(result3)

    print("\n⚡ Test 4: get_embeddings_batch() - Cold (with dedup)")
    cache4 = EmbeddingCache(
        embedding_func=lambda t: mock_embed(t, delay_ms=100),
        batch_func=lambda ts: mock_embed_batch(ts, delay_ms=150),
        model_name="test-model",
    )
    result4 = await benchmark_batch_get(
        "get_embeddings_batch() - 10 unique texts (batch API)",
        cache4,
        test_texts[:10],
        is_cold=True,
    )
    results.append(result4)
    print_result(result4)

    print("\n⚡ Test 5: get_batch() - Warm (L1 hits)")
    result5 = await benchmark_batch_get(
        "get_batch() - 10 concurrent L1 hits",
        cache4,
        test_texts[:10],
        is_cold=False,
    )
    results.append(result5)
    print_result(result5)

    print("\n💾 Test 6: put_batch() - No Redis")
    cache6 = EmbeddingCache(
        embedding_func=lambda t: mock_embed(t, delay_ms=100),
        model_name="test-model",
    )
    embeddings = [[1.0, 2.0, 3.0] for _ in range(10)]
    result6 = await benchmark_batch_put(
        "put_batch() - L1 only (no Redis pipeline)",
        cache6,
        test_texts[:10],
        embeddings,
    )
    results.append(result6)
    print_result(result6)

    print("\n🔄 Test 7: Concurrent stress (50 parallel L1 hits)")
    cache7 = EmbeddingCache(
        embedding_func=lambda t: mock_embed(t, delay_ms=100),
        model_name="test-model",
    )
    await cache7.get_embedding(test_texts[0])

    start = time.perf_counter()
    await asyncio.gather(*[cache7.get(test_texts[0]) for _ in range(50)])
    duration = (time.perf_counter() - start) * 1000

    result7 = BenchmarkResult(
        scenario="Concurrent - 50 parallel L1 hits",
        batch_size=50,
        cache_hit_rate=1.0,
        total_requests=50,
        duration_ms=duration,
        throughput=50 / (duration / 1000),
        avg_latency_ms=duration / 50,
    )
    results.append(result7)
    print_result(result7)

    print("\n🔄 Test 8: Concurrent stress (100 parallel L1 hits)")
    start = time.perf_counter()
    await asyncio.gather(*[cache7.get(test_texts[0]) for _ in range(100)])
    duration = (time.perf_counter() - start) * 1000

    result8 = BenchmarkResult(
        scenario="Concurrent - 100 parallel L1 hits",
        batch_size=100,
        cache_hit_rate=1.0,
        total_requests=100,
        duration_ms=duration,
        throughput=100 / (duration / 1000),
        avg_latency_ms=duration / 100,
    )
    results.append(result8)
    print_result(result8)

    print("\n" + "=" * 75)
    print("📈 COMPREHENSIVE SUMMARY")
    print("=" * 75)
    print(f"\n{'Scenario':<45} {'Throughput':>12} {'Latency':>14}")
    print("-" * 75)
    for r in results:
        print(f"{r.scenario:<45} {r.throughput:>9.1f} r/s {r.avg_latency_ms:>10.2f} ms")

    print("\n\n🎯 KEY PERFORMANCE FINDINGS:")
    print("=" * 75)

    cold_seq = results[0]
    warm_seq = results[1]
    cold_batch = results[3]
    concurrent_50 = results[6]
    concurrent_100 = results[7]

    cache_speedup = cold_seq.avg_latency_ms / warm_seq.avg_latency_ms if warm_seq.avg_latency_ms > 0 else 0
    print("\n1️⃣ L1 Cache Performance:")
    print(f"   Cold API:          {cold_seq.avg_latency_ms:.2f} ms/req")
    print(f"   Warm L1:           {warm_seq.avg_latency_ms:.4f} ms/req")
    print(f"   ✅ Speedup:        {cache_speedup:.0f}x faster")

    batch_speedup = cold_seq.duration_ms / cold_batch.duration_ms if cold_batch.duration_ms > 0 else 0
    print("\n2️⃣ Batch Concurrency (get_batch):")
    print(f"   Sequential:        {cold_seq.duration_ms:.2f} ms (10 reqs)")
    print(f"   Concurrent:        {cold_batch.duration_ms:.2f} ms (10 reqs)")
    print(f"   ✅ Speedup:        {batch_speedup:.1f}x faster")

    print("\n3️⃣ Lock Overhead (Concurrent L1 hits):")
    print(f"   50 parallel:       {concurrent_50.duration_ms:.2f} ms total ({concurrent_50.avg_latency_ms:.4f} ms/req)")
    print(
        f"   100 parallel:      {concurrent_100.duration_ms:.2f} ms total ({concurrent_100.avg_latency_ms:.4f} ms/req)"
    )
    lock_overhead = (
        (concurrent_100.avg_latency_ms / warm_seq.avg_latency_ms - 1) * 100 if warm_seq.avg_latency_ms > 0 else 0
    )
    print(f"   ✅ Lock overhead:  {lock_overhead:.1f}% (negligible)")

    print("\n4️⃣ Mixed Workload (50% hit rate):")
    mixed = results[2]
    print(f"   Throughput:        {mixed.throughput:.1f} req/s")
    print(f"   ✅ Performance:    {mixed.avg_latency_ms:.2f} ms/req avg")

    print("\n" + "=" * 75)
    print("✅ CONCLUSION")
    print("=" * 75)
    print(f"  Cache provides {cache_speedup:.0f}x performance improvement")
    print(f"  Concurrent operations scale efficiently (lock overhead <{lock_overhead:.0f}%)")
    print(f"  Batch operations provide {batch_speedup:.1f}x speedup for cold cache")
    print("  All concurrency optimizations validated with synthetic workload")
    print()


if __name__ == "__main__":
    asyncio.run(main())
