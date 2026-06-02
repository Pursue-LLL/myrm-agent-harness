"""Benchmark compression levels to validate performance claims.

This benchmark verifies the actual performance characteristics of different
compression levels to ensure documentation accuracy.
"""

from __future__ import annotations

import time

from myrm_agent_harness.runtime.compression import compress_content


def benchmark_compression_levels() -> None:
    """Benchmark compression levels with different file sizes."""
    # Test data with different sizes and repetition patterns
    test_cases = [
        ("Small (30KB)", "A" * 30000),
        ("Medium (200KB)", "B" * 200000),
        ("Large (600KB)", "C" * 600000),
        ("HTML-like (100KB)", "<div>Content</div>" * 5000),
    ]

    levels_to_test = [1, 6, 9]

    print("=" * 80)
    print("Compression Level Performance Benchmark")
    print("=" * 80)
    print()

    for test_name, content in test_cases:
        print(f"\n{test_name} ({len(content):,} bytes):")
        print("-" * 60)

        results = {}
        for level in levels_to_test:
            # Warmup
            for _ in range(3):
                compress_content(content, level=level)

            # Benchmark
            iterations = 10
            start = time.perf_counter()
            compressed_sizes = []
            for _ in range(iterations):
                compressed = compress_content(content, level=level)
                compressed_sizes.append(len(compressed))
            duration = time.perf_counter() - start

            avg_time = duration / iterations * 1000  # ms
            avg_size = sum(compressed_sizes) / len(compressed_sizes)
            compression_ratio = len(content) / avg_size

            results[level] = {
                "time_ms": avg_time,
                "size": avg_size,
                "ratio": compression_ratio,
            }

            print(f"  Level {level}: {avg_time:.3f}ms, {avg_size:,.0f} bytes, ratio: {compression_ratio:.2f}x")

        # Calculate speedup and compression improvement
        if 1 in results and 6 in results:
            speedup_1_vs_6 = results[6]["time_ms"] / results[1]["time_ms"]
            print(f"\n  Speed: Level 1 is {speedup_1_vs_6:.2f}x faster than Level 6")

        if 6 in results and 9 in results:
            ratio_improvement = (results[9]["ratio"] - results[6]["ratio"]) / results[6]["ratio"] * 100
            time_overhead = (results[9]["time_ms"] - results[6]["time_ms"]) / results[6]["time_ms"] * 100
            print(f"  Compression: Level 9 is {ratio_improvement:.1f}% better than Level 6")
            print(f"  Time cost: Level 9 is {time_overhead:.1f}% slower than Level 6")

    print("\n" + "=" * 80)
    print("Benchmark Complete")
    print("=" * 80)


if __name__ == "__main__":
    benchmark_compression_levels()
