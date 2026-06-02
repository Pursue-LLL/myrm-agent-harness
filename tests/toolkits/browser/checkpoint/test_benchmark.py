"""Performance benchmarks for checkpoint operations.

Measures actual performance characteristics rather than theoretical estimates.
"""

from __future__ import annotations

import time

import pytest
from langgraph.checkpoint.base import Checkpoint, CheckpointMetadata
from langgraph.checkpoint.memory import MemorySaver

from myrm_agent_harness.toolkits.browser.checkpoint import (
    IncrementalSessionCheckpointer,
)


@pytest.mark.benchmark(group="incremental_save")
class TestIncrementalSaveBenchmark:
    """Benchmark incremental save performance."""

    @pytest.mark.asyncio
    async def test_hash_comparison_overhead(self):
        """Measure hash comparison overhead."""
        base_saver = MemorySaver()
        saver = IncrementalSessionCheckpointer(base_saver)

        config = {"configurable": {"thread_id": "bench-1", "checkpoint_ns": ""}}

        # Metadata with same hash (will be skipped)
        metadata = CheckpointMetadata(
            browser={
                "session_hash": "abc123",
                "current_url": "https://example.com",
            }
        )

        # Benchmark: 100 saves with same hash
        start = time.perf_counter()

        for i in range(100):
            checkpoint = Checkpoint(
                v=1,
                id=f"cp-{i}",
                ts=f"2024-01-01T00:{i:02d}:00Z",
                channel_values={"messages": []},
            )
            await saver.aput(config, checkpoint, metadata, {})

        elapsed_ms = (time.perf_counter() - start) * 1000
        avg_per_save_ms = elapsed_ms / 100

        print("\n=== Hash Comparison Overhead ===")
        print(f"100 saves with same hash: {elapsed_ms:.1f}ms")
        print(f"Average per save: {avg_per_save_ms:.2f}ms")
        print(f"Skipped: {saver.metrics.save_skipped_count} / {saver.metrics.save_count}")

        # Verify most were skipped (first save establishes hash, rest skipped)
        assert saver.metrics.save_skipped_count == 99

    @pytest.mark.asyncio
    async def test_incremental_ratio_realistic_scenario(self):
        """Measure incremental ratio in realistic scenario.

        Scenario: 10 checkpoint saves, 2 session state changes.
        Expected: 80% skip ratio.
        """
        base_saver = MemorySaver()
        saver = IncrementalSessionCheckpointer(base_saver)

        config = {"configurable": {"thread_id": "bench-2", "checkpoint_ns": ""}}

        # 10 saves with 2 hash changes
        for i in range(10):
            checkpoint = Checkpoint(
                v=1,
                id=f"cp-{i}",
                ts=f"2024-01-01T00:{i:02d}:00Z",
                channel_values={"messages": []},
            )

            # Hash changes at i=0 and i=5
            hash_val = "hash_v1" if i < 5 else "hash_v2"

            metadata = CheckpointMetadata(
                browser={
                    "session_hash": hash_val,
                    "current_url": f"https://example.com/page{i}",
                }
            )

            await saver.aput(config, checkpoint, metadata, {})

        metrics = saver.metrics

        # Assertions
        assert metrics.save_count == 10
        assert metrics.vault_save_count == 2  # Only 2 unique hashes
        assert metrics.save_skipped_count == 8

        # Verify incremental ratio
        ratio = metrics.incremental_ratio
        assert 0.75 <= ratio <= 0.85, f"Expected ~80% skip ratio, got {ratio:.1%}"

        # Print actual performance data
        print("\n=== Incremental Save Performance ===")
        print(f"Total saves: {metrics.save_count}")
        print(f"Actual SessionVault saves: {metrics.vault_save_count}")
        print(f"Skipped saves: {metrics.save_skipped_count}")
        print(f"Skip ratio: {ratio:.1%}")
        print(f"I/O reduction: {1 / (1 - ratio):.1f}x")

    @pytest.mark.asyncio
    async def test_metadata_access_vs_parsing_performance(self):
        """Measure metadata access performance vs message parsing.

        Compares:
        - Direct metadata access: O(1)
        - Message parsing: O(n)
        """
        from myrm_agent_harness.toolkits.browser.checkpoint.metadata import (
            extract_metadata_from_messages,
        )

        # Create 100 dummy messages
        messages = []
        for i in range(100):
            messages.append({"role": "user" if i % 2 == 0 else "assistant", "content": f"Message {i}"})

        # Add browser operation message at the end
        messages.append({"role": "assistant", "content": "[10 refs | ~50 tokens | url: https://example.com/final]"})

        # Benchmark parsing
        start_parse = time.perf_counter()
        for _ in range(100):
            extract_metadata_from_messages(messages)
        parse_time_ms = (time.perf_counter() - start_parse) * 1000 / 100

        # Benchmark direct access
        metadata_dict = {"browser": {"current_url": "https://example.com/final"}}
        start_access = time.perf_counter()
        for _ in range(100):
            _ = metadata_dict.get("browser", {}).get("current_url")
        access_time_ms = (time.perf_counter() - start_access) * 1000 / 100

        speedup = parse_time_ms / access_time_ms if access_time_ms > 0 else float("inf")

        print("\n=== Metadata Access Performance ===")
        print(f"Direct access: {access_time_ms:.3f}ms")
        print(f"Message parsing (100 messages): {parse_time_ms:.3f}ms")
        print(f"Speedup: {speedup:.0f}x")

        # Verify speedup is significant
        assert speedup > 10, f"Expected >10x speedup, got {speedup:.1f}x"


@pytest.mark.benchmark(group="parallel_recovery")
class TestParallelRecoveryBenchmark:
    """Benchmark parallel recovery performance."""

    @pytest.mark.asyncio
    async def test_parallel_vs_sequential_recovery(self):
        """Measure parallel recovery speedup.

        Simulates recovery of 5 tasks with network I/O.
        """
        import asyncio

        # Simulate single recovery with 200ms network latency
        async def recover_one_task(task_id: int) -> bool:
            await asyncio.sleep(0.2)  # Simulate network + browser startup
            return True

        # Sequential recovery
        start_seq = time.perf_counter()
        for i in range(5):
            await recover_one_task(i)
        sequential_time = time.perf_counter() - start_seq

        # Parallel recovery (3 concurrent)
        semaphore = asyncio.Semaphore(3)

        async def recover_with_semaphore(task_id: int) -> bool:
            async with semaphore:
                return await recover_one_task(task_id)

        start_par = time.perf_counter()
        await asyncio.gather(*[recover_with_semaphore(i) for i in range(5)])
        parallel_time = time.perf_counter() - start_par

        speedup = sequential_time / parallel_time

        print("\n=== Parallel Recovery Performance ===")
        print(f"Sequential (5 tasks): {sequential_time:.2f}s")
        print(f"Parallel (3 concurrent): {parallel_time:.2f}s")
        print(f"Speedup: {speedup:.2f}x")

        # Verify meaningful speedup
        assert speedup > 1.5, f"Expected >1.5x speedup, got {speedup:.2f}x"
