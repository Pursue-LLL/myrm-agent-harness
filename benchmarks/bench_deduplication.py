"""Benchmark deduplication hash performance.

Compares MD5 vs SHA256 for message deduplication.
"""

import hashlib
import json
import time
from typing import Any


def hash_with_sha256(data: dict[str, Any]) -> str:
    """Hash using SHA256."""
    data_str = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(data_str.encode()).hexdigest()


def hash_with_md5(data: dict[str, Any]) -> str:
    """Hash using MD5."""
    data_str = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(data_str.encode(), usedforsecurity=False).hexdigest()


def benchmark_hash_algorithms(iterations: int = 100000) -> None:
    """Benchmark hash algorithms."""
    # Sample data (realistic message size)
    test_data = {
        "channel": "telegram",
        "recipient": "user123",
        "content": {
            "text": "Hello world! This is a test message with some content. " * 10,
            "metadata": {"timestamp": 1234567890, "source": "api"},
        },
    }

    # Benchmark SHA256
    start = time.perf_counter()
    for _ in range(iterations):
        hash_with_sha256(test_data)
    sha256_time = time.perf_counter() - start

    # Benchmark MD5
    start = time.perf_counter()
    for _ in range(iterations):
        hash_with_md5(test_data)
    md5_time = time.perf_counter() - start

    # Results
    print(f"\n{'=' * 60}")
    print("Deduplication Hash Algorithm Benchmark")
    print(f"{'=' * 60}")
    print(f"Iterations: {iterations:,}")
    print("\nSHA256:")
    print(f"  Total time: {sha256_time:.4f}s")
    print(f"  Per operation: {sha256_time / iterations * 1000:.4f}ms")
    print("\nMD5:")
    print(f"  Total time: {md5_time:.4f}s")
    print(f"  Per operation: {md5_time / iterations * 1000:.4f}ms")
    print(f"\nSpeedup: {sha256_time / md5_time:.2f}x faster")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    benchmark_hash_algorithms()
