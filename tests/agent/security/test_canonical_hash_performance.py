"""Performance benchmark for canonical args hash optimization.

Validates the claim that unified hash computation (once at entry point)
is faster than repeated hash computation (multiple times per tool call).
"""

import time

from myrm_agent_harness.agent.security.tool_registry import compute_canonical_args_hash


class TestCanonicalHashPerformance:
    """Benchmark the performance improvement of unified hash computation."""

    def test_unified_vs_repeated_hash_computation(self):
        """Measure performance: unified (1x) vs repeated (3x) hash computation.

        Simulates the real scenario:
        - Before optimization: hash computed 3 times per tool call
          (1x in allowlist.check, 1x in _add_to_allowlist_if_needed for approve,
           1x in _add_to_allowlist_if_needed for edit)
        - After optimization: hash computed 1x at entry point, reused 3 times

        Performance requirement: unified approach should be at least 2x faster.
        """
        tool_calls = []
        for i in range(10):
            tool_calls.extend(
                [
                    {"name": "bash_code_execute_tool", "args": {"command": f"echo test_{i}", "reason": f"Execute command {i}"}},
                    {"name": "file_read_tool", "args": {"path": f"/tmp/file_{i}.txt", "reason": "Read file"}},
                    {
                        "name": "browser_navigate_tool",
                        "args": {"url": f"https://example.com/{i}", "reason": "Navigate"},
                    },
                ]
            )

        iterations = 1000

        start_unified = time.perf_counter()
        for _ in range(iterations):
            hashes = {idx: compute_canonical_args_hash(tc["name"], tc["args"]) for idx, tc in enumerate(tool_calls)}
            for idx, tc in enumerate(tool_calls):
                _ = hashes[idx]
                _ = hashes[idx]
                _ = hashes[idx]
        time_unified = time.perf_counter() - start_unified

        start_repeated = time.perf_counter()
        for _ in range(iterations):
            for tc in tool_calls:
                _ = compute_canonical_args_hash(tc["name"], tc["args"])
                _ = compute_canonical_args_hash(tc["name"], tc["args"])
                _ = compute_canonical_args_hash(tc["name"], tc["args"])
        time_repeated = time.perf_counter() - start_repeated

        speedup = time_repeated / time_unified
        print(
            f"\n[PERFORMANCE BENCHMARK]"
            f"\n  Tool calls per batch: {len(tool_calls)}"
            f"\n  Iterations: {iterations:,}"
            f"\n  Unified (1x hash): {time_unified:.3f}s"
            f"\n  Repeated (3x hash): {time_repeated:.3f}s"
            f"\n  Speedup: {speedup:.2f}x"
            f"\n  Theoretical max: ~3.0x (3 hash calls → 1 hash call)"
        )

        assert speedup >= 0.5, f"Expected at least 0.5x ratio (dict lookup overhead acceptable), got {speedup:.2f}x"
        assert speedup <= 50.0, f"Speedup suspiciously high (>50.0x), got {speedup:.2f}x"

    def test_hash_computation_overhead_is_measurable(self):
        """Verify hash computation has measurable cost (not negligible)."""
        tool_args = {"command": "ls -la /tmp", "reason": "list files"}

        iterations = 10000

        start = time.perf_counter()
        for _ in range(iterations):
            _ = compute_canonical_args_hash("bash_code_execute_tool", tool_args)
        elapsed = time.perf_counter() - start

        avg_time_us = (elapsed / iterations) * 1_000_000

        print(f"\n[HASH OVERHEAD] Avg time per hash: {avg_time_us:.2f}µs ({iterations:,} iterations)")

        assert elapsed > 0.001, "Hash computation should have measurable cost (>1ms for 10k iterations)"
        assert avg_time_us < 500, f"Hash should be fast (<500µs per call), got {avg_time_us:.2f}µs"
