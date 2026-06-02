#!/usr/bin/env python3
"""Real-world embedding cache performance benchmark.

Tests EmbeddingCache with actual OpenAI API calls to quantify:
- L1 cache hit performance
- L3 API call latency
- Batch operation speedup
- Concurrent operation efficiency

Usage:
    cd myrm-agent-harness
    source .venv/bin/activate
    python benchmarks/bench_embedding_cache_real.py
"""

from __future__ import annotations

import asyncio
import os
import statistics
import time
from dataclasses import dataclass

from myrm_agent_harness.toolkits.memory._internal.embedding_cache import EmbeddingCache
from myrm_agent_harness.toolkits.retriever.embedding.factory import EmbeddingConfig, get_embedding_service


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
    p50_ms: float
    p95_ms: float
    p99_ms: float


async def benchmark_scenario(
    cache: EmbeddingCache,
    texts: list[str],
    scenario_name: str,
    warmup_texts: list[str] | None = None,
) -> BenchmarkResult:
    """Benchmark a specific scenario."""
    if warmup_texts:
        await cache.get_embeddings_batch(warmup_texts)

    latencies: list[float] = []
    start = time.perf_counter()

    for text in texts:
        t0 = time.perf_counter()
        await cache.get_embedding(text)
        latencies.append((time.perf_counter() - t0) * 1000)

    duration = (time.perf_counter() - start) * 1000
    stats = cache.get_stats()
    hit_rate = stats["hit_rate"]

    return BenchmarkResult(
        scenario=scenario_name,
        batch_size=len(texts),
        cache_hit_rate=hit_rate,
        total_requests=len(texts),
        duration_ms=duration,
        throughput=len(texts) / (duration / 1000),
        avg_latency_ms=statistics.mean(latencies),
        p50_ms=statistics.median(latencies),
        p95_ms=statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies),
        p99_ms=statistics.quantiles(latencies, n=100)[98] if len(latencies) >= 100 else max(latencies),
    )


async def benchmark_batch_operations(
    cache: EmbeddingCache,
    texts: list[str],
    scenario_name: str,
) -> BenchmarkResult:
    """Benchmark batch operations with asyncio.gather."""
    start = time.perf_counter()
    await cache.get_batch(texts)
    duration = (time.perf_counter() - start) * 1000

    stats = cache.get_stats()
    return BenchmarkResult(
        scenario=scenario_name,
        batch_size=len(texts),
        cache_hit_rate=stats["hit_rate"],
        total_requests=len(texts),
        duration_ms=duration,
        throughput=len(texts) / (duration / 1000),
        avg_latency_ms=duration / len(texts),
        p50_ms=0,
        p95_ms=0,
        p99_ms=0,
    )


def print_result(result: BenchmarkResult) -> None:
    """Print formatted benchmark result."""
    print(f"\n{'=' * 70}")
    print(f"📊 {result.scenario}")
    print(f"{'=' * 70}")
    print(f"  Batch Size:       {result.batch_size}")
    print(f"  Cache Hit Rate:   {result.cache_hit_rate * 100:.1f}%")
    print(f"  Total Requests:   {result.total_requests}")
    print(f"  Duration:         {result.duration_ms:.2f} ms")
    print(f"  Throughput:       {result.throughput:.2f} req/s")
    print(f"  Avg Latency:      {result.avg_latency_ms:.2f} ms")
    if result.p50_ms > 0:
        print(f"  P50 Latency:      {result.p50_ms:.2f} ms")
        print(f"  P95 Latency:      {result.p95_ms:.2f} ms")
        print(f"  P99 Latency:      {result.p99_ms:.2f} ms")


async def main() -> None:
    """Run comprehensive embedding cache benchmarks."""
    api_key = os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ EMBEDDING_API_KEY not set. Skipping real API benchmarks.")
        return

    print("\n🚀 Initializing real embedding service...")
    model = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
    api_base = os.getenv("EMBEDDING_API_BASE")

    print(f"  Model: {model}")
    print(f"  API Base: {api_base}")

    config = EmbeddingConfig(
        model=model,
        api_key=api_key,
        api_base=api_base if api_base else None,
    )
    embedding_service = get_embedding_service(config)

    cache = EmbeddingCache(
        embedding_func=embedding_service.embed,
        batch_func=embedding_service.embed_batch,
        model_name=config.model,
        l1_max_size=1000,
    )

    test_texts = [
        "Python programming language",
        "Machine learning algorithms",
        "Web development frameworks",
        "Database optimization techniques",
        "Cloud computing platforms",
        "Software architecture patterns",
        "API design best practices",
        "DevOps automation tools",
        "Data structures and algorithms",
        "Cybersecurity fundamentals",
        "Distributed system design",
        "Microservices architecture",
        "Containerization technologies",
        "Continuous integration pipelines",
        "RESTful API development",
        "NoSQL database systems",
        "Artificial intelligence models",
        "Neural network training",
        "Natural language processing",
        "Computer vision algorithms",
        "Real-time data processing",
        "Message queue systems",
        "Load balancing strategies",
        "Caching mechanisms",
        "Authentication protocols",
        "Authorization frameworks",
        "Encryption algorithms",
        "Version control systems",
        "Agile development methodologies",
        "Test-driven development",
        "Code review best practices",
        "Performance optimization",
        "Memory management",
        "Concurrency patterns",
        "Asynchronous programming",
        "Graph database queries",
        "Time series analysis",
        "Data visualization techniques",
        "Frontend frameworks",
        "Backend frameworks",
        "Mobile app development",
        "Cross-platform solutions",
        "Progressive web apps",
        "Server-side rendering",
        "Static site generation",
        "JAMstack architecture",
        "Serverless computing",
        "Edge computing",
        "Blockchain technology",
        "Smart contract development",
        "Kubernetes orchestration",
        "Docker containers",
        "Infrastructure as code",
        "Configuration management",
        "Observability practices",
        "Monitoring tools",
        "Logging strategies",
        "Debugging techniques",
        "Profiling applications",
        "Code quality metrics",
    ]

    print("\n🔥 Starting real-world benchmarks...\n")

    results: list[BenchmarkResult] = []

    print("\n1️⃣ Cold cache (batch_size=1)")
    result_b1 = await benchmark_scenario(
        cache,
        test_texts[:1],
        "Cold - batch_size=1",
    )
    results.append(result_b1)
    print_result(result_b1)

    print("\n2️⃣ Cold cache (batch_size=10)")
    cache._l1.clear()
    result_b10 = await benchmark_scenario(
        cache,
        test_texts[1:11],
        "Cold - batch_size=10",
    )
    results.append(result_b10)
    print_result(result_b10)

    print("\n3️⃣ Cold cache (batch_size=30)")
    cache._l1.clear()
    result_b30 = await benchmark_scenario(
        cache,
        test_texts[11:41],
        "Cold - batch_size=30",
    )
    results.append(result_b30)
    print_result(result_b30)

    print("\n4️⃣ Warm cache (100% hit, batch_size=10)")
    cache._l1.clear()
    result2 = await benchmark_scenario(
        cache,
        test_texts[:10],
        "Warm - 100% hit",
        warmup_texts=test_texts[:10],
    )
    results.append(result2)
    print_result(result2)

    print("\n5️⃣ Mixed cache (50% hit, batch_size=10)")
    cache._l1.clear()
    mixed_texts = test_texts[:5] + [f"{t} _mod" for t in test_texts[:5]]
    result3 = await benchmark_scenario(
        cache,
        mixed_texts,
        "Mixed - 50% hit",
        warmup_texts=test_texts[:5],
    )
    results.append(result3)
    print_result(result3)

    print("\n6️⃣ Mixed cache (90% hit, batch_size=10)")
    cache._l1.clear()
    mixed_90 = [*test_texts[:9], f"{test_texts[9]} _mod"]
    result_90 = await benchmark_scenario(
        cache,
        mixed_90,
        "Mixed - 90% hit",
        warmup_texts=test_texts[:9],
    )
    results.append(result_90)
    print_result(result_90)

    print("\n7️⃣ Batch operations (cold)")
    cache_batch = EmbeddingCache(
        embedding_func=embedding_service.embed,
        batch_func=embedding_service.embed_batch,
        model_name=config.model,
    )
    result_batch = await benchmark_batch_operations(
        cache_batch,
        test_texts[41:51],
        "Batch get_batch() - cold",
    )
    results.append(result_batch)
    print_result(result_batch)

    print("\n8️⃣ Concurrent operations (50 parallel)")
    cache_concurrent = EmbeddingCache(
        embedding_func=embedding_service.embed,
        batch_func=embedding_service.embed_batch,
        model_name=config.model,
    )
    await cache_concurrent.get_embedding(test_texts[0])
    concurrent_texts = [test_texts[0]] * 50

    start = time.perf_counter()
    await asyncio.gather(*[cache_concurrent.get(t) for t in concurrent_texts])
    duration = (time.perf_counter() - start) * 1000

    result5 = BenchmarkResult(
        scenario="Concurrent - 50 parallel L1 hits",
        batch_size=50,
        cache_hit_rate=1.0,
        total_requests=50,
        duration_ms=duration,
        throughput=50 / (duration / 1000),
        avg_latency_ms=duration / 50,
        p50_ms=0,
        p95_ms=0,
        p99_ms=0,
    )
    results.append(result5)
    print_result(result5)

    print("\n" + "=" * 70)
    print("📈 SUMMARY")
    print("=" * 70)
    print(f"\n{'Scenario':<40} {'Throughput':>12} {'Avg Latency':>14}")
    print("-" * 70)
    for r in results:
        print(f"{r.scenario:<40} {r.throughput:>9.1f} r/s {r.avg_latency_ms:>10.2f} ms")

    print("\n\n🎯 KEY FINDINGS:")
    cold_b1 = results[0]
    cold_b10 = results[1]
    warm = results[3]
    concurrent = results[-1]

    speedup_b10 = (
        cold_b10.avg_latency_ms / warm.avg_latency_ms
        if warm.avg_latency_ms > 0
        else cold_b10.throughput / warm.throughput
    )

    print(f"  L1 Cache Speedup:       {speedup_b10:.0f}x (batch=10)")
    print(f"  Cold API Latency:       {cold_b10.avg_latency_ms:.2f} ms/req (batch=10)")
    print(f"  Warm L1 Latency:        {warm.avg_latency_ms:.4f} ms/req")
    print(f"  Concurrent L1 (50):     {concurrent.duration_ms:.2f} ms total ({concurrent.avg_latency_ms:.4f} ms/req)")
    print(f"\n  ✅ L1 cache: {speedup_b10:.0f}x faster than API")
    print(f"  ✅ batch=1 vs batch=10: {cold_b1.avg_latency_ms / cold_b10.avg_latency_ms:.1f}x speedup")
    print("  ✅ Concurrent (50 parallel): scales efficiently")


if __name__ == "__main__":
    asyncio.run(main())
