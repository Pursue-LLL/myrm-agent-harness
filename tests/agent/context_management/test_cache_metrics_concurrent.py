"""Concurrent NDJSON write tests for cache metrics collector.

Validates thread-safe file writes under multi-threaded LLM response logging scenarios.
"""

from __future__ import annotations

import concurrent.futures
import json
import threading
import time
from collections.abc import Generator
from pathlib import Path

import pytest

from myrm_agent_harness.agent.context_management.infra.cache_metrics_collector import (
    PendingExplicitCacheSnapshot,
    set_pending_explicit_cache_snapshot,
    try_persist_cache_call_metrics,
)


@pytest.fixture
def metrics_dir(tmp_path: Path) -> Generator[Path]:
    """Setup temporary metrics directory."""
    from myrm_agent_harness.agent.context_management.infra.cache_metrics_collector import set_cache_metrics_dir

    metrics_path = tmp_path / "metrics"
    set_cache_metrics_dir(str(metrics_path))
    yield metrics_path
    set_cache_metrics_dir(None)


def _mock_llm_response(
    prompt_tokens: int, completion_tokens: int, cached_tokens: int, model: str = "anthropic/claude-3-5-sonnet"
) -> dict[str, object]:
    """Create mock LLM response for testing."""
    return {
        "model": model,
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "prompt_tokens_details": {"cached_tokens": cached_tokens},
        },
    }


def test_concurrent_writes_no_corruption(metrics_dir: Path) -> None:
    """Concurrent writes from multiple threads produce valid NDJSON without corruption.

    Evidence: Threading.Lock ensures atomic append operations. All records are valid
    JSON and no partial/interleaved writes occur.
    """
    num_threads = 10
    writes_per_thread = 20

    def worker(thread_id: int) -> None:
        for i in range(writes_per_thread):
            snapshot = PendingExplicitCacheSnapshot(
                turn_count=thread_id * writes_per_thread + i,
                breakpoint_count=3,
                message_count=15,
                total_estimated_tokens=8000,
                expected_cacheable_tokens=4000,
                compression_count=0,
            )
            set_pending_explicit_cache_snapshot(snapshot)
            response = _mock_llm_response(prompt_tokens=8000, completion_tokens=1000, cached_tokens=4000)
            try_persist_cache_call_metrics(response)

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, tid) for tid in range(num_threads)]
        concurrent.futures.wait(futures)

    ndjson_files = list(metrics_dir.glob("cache_metrics_*.ndjson"))
    assert len(ndjson_files) == 1, f"Expected 1 NDJSON file, got {len(ndjson_files)}"

    ndjson_file = ndjson_files[0]
    lines = ndjson_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == num_threads * writes_per_thread

    for line_idx, line in enumerate(lines):
        try:
            record = json.loads(line)
            assert "turn_count" in record["explicit_cache"]
            assert record["prompt_tokens"] == 8000
            assert record["cached_tokens"] == 4000
        except json.JSONDecodeError as e:
            pytest.fail(f"Line {line_idx} is not valid JSON: {e}")


def test_concurrent_writes_unique_records(metrics_dir: Path) -> None:
    """Each thread's records are distinct and all turn_count values are unique.

    Evidence: No data loss or duplicate records occur under concurrent writes.
    """
    num_threads = 8
    writes_per_thread = 15

    def worker(thread_id: int) -> None:
        for i in range(writes_per_thread):
            unique_turn = thread_id * 1000 + i
            snapshot = PendingExplicitCacheSnapshot(
                turn_count=unique_turn,
                breakpoint_count=2,
                message_count=10,
                total_estimated_tokens=5000,
                expected_cacheable_tokens=2500,
                compression_count=0,
            )
            set_pending_explicit_cache_snapshot(snapshot)
            response = _mock_llm_response(prompt_tokens=5000, completion_tokens=800, cached_tokens=2500)
            try_persist_cache_call_metrics(response)

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, tid) for tid in range(num_threads)]
        concurrent.futures.wait(futures)

    ndjson_file = next(metrics_dir.glob("cache_metrics_*.ndjson"))
    lines = ndjson_file.read_text(encoding="utf-8").strip().split("\n")

    turn_counts = set()
    for line in lines:
        record = json.loads(line)
        turn_count = record["explicit_cache"]["turn_count"]
        assert turn_count not in turn_counts, f"Duplicate turn_count: {turn_count}"
        turn_counts.add(turn_count)

    assert len(turn_counts) == num_threads * writes_per_thread


def test_concurrent_writes_with_snapshot_clearing(metrics_dir: Path) -> None:
    """Concurrent writes with snapshot clearing maintain correctness.

    Evidence: ContextVar isolation ensures snapshots don't leak between threads.
    """
    num_threads = 5
    writes_per_thread = 10
    thread_local_counters = {}
    counter_lock = threading.Lock()

    def worker(thread_id: int) -> None:
        local_count = 0
        for i in range(writes_per_thread):
            if i % 2 == 0:
                snapshot = PendingExplicitCacheSnapshot(
                    turn_count=thread_id * 100 + i,
                    breakpoint_count=3,
                    message_count=12,
                    total_estimated_tokens=6000,
                    expected_cacheable_tokens=3000,
                    compression_count=0,
                )
                set_pending_explicit_cache_snapshot(snapshot)
                local_count += 1

            response = _mock_llm_response(prompt_tokens=6000, completion_tokens=900, cached_tokens=3000)
            try_persist_cache_call_metrics(response)

        with counter_lock:
            thread_local_counters[thread_id] = local_count

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, tid) for tid in range(num_threads)]
        concurrent.futures.wait(futures)

    ndjson_file = next(metrics_dir.glob("cache_metrics_*.ndjson"))
    lines = ndjson_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == num_threads * writes_per_thread

    records_with_snapshot = sum(1 for line in lines if json.loads(line)["explicit_cache_snapshot"] is True)
    expected_snapshot_count = sum(thread_local_counters.values())
    assert records_with_snapshot == expected_snapshot_count


def test_high_contention_write_performance(metrics_dir: Path) -> None:
    """Benchmark: High contention (20 threads) maintains throughput >500 writes/sec.

    Evidence: Threading.Lock overhead is minimal. Even with 20 concurrent threads,
    aggregate throughput exceeds 500 writes/second.
    """
    num_threads = 20
    writes_per_thread = 50
    total_writes = num_threads * writes_per_thread

    def worker(thread_id: int) -> None:
        for i in range(writes_per_thread):
            snapshot = PendingExplicitCacheSnapshot(
                turn_count=thread_id * writes_per_thread + i,
                breakpoint_count=2,
                message_count=8,
                total_estimated_tokens=4000,
                expected_cacheable_tokens=2000,
                compression_count=0,
            )
            set_pending_explicit_cache_snapshot(snapshot)
            response = _mock_llm_response(prompt_tokens=4000, completion_tokens=700, cached_tokens=2000)
            try_persist_cache_call_metrics(response)

    start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, tid) for tid in range(num_threads)]
        concurrent.futures.wait(futures)
    elapsed = time.perf_counter() - start

    throughput = total_writes / elapsed
    assert throughput > 500.0, f"Throughput {throughput:.0f} writes/s below 500/s threshold"

    ndjson_file = next(metrics_dir.glob("cache_metrics_*.ndjson"))
    lines = ndjson_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == total_writes


def test_context_var_isolation_across_threads(metrics_dir: Path) -> None:
    """ContextVar isolation ensures snapshots don't leak between threads.

    Evidence: Each thread's snapshot is isolated. Thread A's snapshot does not affect
    Thread B's metrics even when writes are interleaved.
    """
    results: dict[int, list[int]] = {}
    results_lock = threading.Lock()

    def worker(thread_id: int) -> None:
        local_turns: list[int] = []
        for i in range(5):
            unique_turn = thread_id * 1000 + i
            snapshot = PendingExplicitCacheSnapshot(
                turn_count=unique_turn,
                breakpoint_count=3,
                message_count=10,
                total_estimated_tokens=5000,
                expected_cacheable_tokens=2500,
                compression_count=0,
            )
            set_pending_explicit_cache_snapshot(snapshot)
            local_turns.append(unique_turn)

            response = _mock_llm_response(prompt_tokens=5000, completion_tokens=800, cached_tokens=2500)
            try_persist_cache_call_metrics(response)

        with results_lock:
            results[thread_id] = local_turns

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(worker, tid) for tid in range(4)]
        concurrent.futures.wait(futures)

    ndjson_file = next(metrics_dir.glob("cache_metrics_*.ndjson"))
    lines = ndjson_file.read_text(encoding="utf-8").strip().split("\n")

    for _thread_id, expected_turns in results.items():
        thread_records = [
            json.loads(line) for line in lines if json.loads(line)["explicit_cache"]["turn_count"] in expected_turns
        ]
        assert len(thread_records) == len(expected_turns)
        actual_turns = [rec["explicit_cache"]["turn_count"] for rec in thread_records]
        assert set(actual_turns) == set(expected_turns)
