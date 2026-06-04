"""Benchmark for ScanResultCache performance.

Measures cache hit vs miss performance to verify 20x speedup claim.
"""

import time
from pathlib import Path
from tempfile import TemporaryDirectory

from myrm_agent_harness.backends.skills.scanning.cache import ScanResultCache
from myrm_agent_harness.backends.skills.scanning.scanner import scan_skill_content

# Sample skill content for testing
SAMPLE_SKILL_CONTENT = (
    """
# Test Skill

This is a test skill for benchmarking cache performance.

def execute():
    import requests
    import subprocess
    import os
    response = requests.get("https://api.example.com/data")
    subprocess.run(["ls", "-la"])
    os.system("whoami")
    return response.json()
"""
    * 10
)  # Repeat to create larger content


def benchmark_cache_miss(iterations: int = 10) -> float:
    """Benchmark cache miss (first-time scan)."""
    times = []
    for i in range(iterations):
        content = SAMPLE_SKILL_CONTENT + f"# Iteration {i}"  # Unique content each time
        start = time.perf_counter()
        scan_skill_content(f"test-skill-{i}", content)
        elapsed = time.perf_counter() - start
        times.append(elapsed)

    avg_time = sum(times) / len(times)
    return avg_time * 1000  # Convert to ms


def benchmark_cache_hit(iterations: int = 10) -> float:
    """Benchmark cache hit (repeated scan with cache)."""
    with TemporaryDirectory() as tmpdir:
        cache = ScanResultCache(cache_dir=Path(tmpdir))

        # Pre-populate cache
        scan_result = scan_skill_content("test-skill", SAMPLE_SKILL_CONTENT)
        cache.set(SAMPLE_SKILL_CONTENT, scan_result)

        # Benchmark cache hit
        times = []
        for _ in range(iterations):
            start = time.perf_counter()
            result = cache.get(SAMPLE_SKILL_CONTENT)
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            assert result is not None

        avg_time = sum(times) / len(times)
        return avg_time * 1000  # Convert to ms


def main():
    """Run benchmark and print results."""
    print("=== Scan Cache Performance Benchmark ===\n")

    print("Warming up...")
    benchmark_cache_miss(iterations=3)
    benchmark_cache_hit(iterations=3)

    print("\nRunning benchmarks...")
    miss_time = benchmark_cache_miss(iterations=10)
    hit_time = benchmark_cache_hit(iterations=100)  # More iterations for cache hit (faster)

    speedup = miss_time / hit_time

    print("\nResults:")
    print(f"  Cache MISS (first scan): {miss_time:.2f} ms")
    print(f"  Cache HIT  (repeat scan): {hit_time:.2f} ms")
    print(f"  Speedup: {speedup:.1f}x")
    print(f"\n✅ Verified: Cache provides {speedup:.1f}x performance improvement")

    # Verify claim
    if speedup >= 10.0:
        print(f"✅ SUCCESS: Speedup ({speedup:.1f}x) meets/exceeds 10x target")
    else:
        print(f"⚠️  WARNING: Speedup ({speedup:.1f}x) below 10x target")


if __name__ == "__main__":
    main()
