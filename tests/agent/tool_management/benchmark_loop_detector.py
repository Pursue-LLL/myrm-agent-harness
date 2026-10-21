"""Performance benchmark for LoopGuard.

Measures actual performance across all detection modes:
- Per-call detection latency
- Throughput (calls/sec)
- Individual mode performance breakdown

Methodology:
- 100,000 iterations with 10,000 warmup
- 3 runs averaged
- Includes all detection modes and metrics tracking
"""

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from myrm_agent_harness.agent.security.guards.loop_guard import LoopGuard


def benchmark_full_detection() -> dict[str, float]:
    """Benchmark full detection cycle with all features enabled."""
    guard = LoopGuard(
        window_size=20,
        warn_threshold=3,
        break_threshold=5,
        ping_pong_cycles=3,
        no_progress_threshold=4,
        divergence_threshold=6,
        enable_stats=False,
    )

    warmup_iterations = 10_000
    test_iterations = 100_000

    test_tools = [
        ("file_read_tool", {"path": "/foo/bar.py"}),
        ("memory_search_tool", {"query": "test", "limit": 5}),
        ("bash_code_execute_tool", {"command": "ls -la"}),
        ("web_search_tool", {"questions": ["python async"]}),
        ("file_write_tool", {"path": "/tmp/test.txt", "content": "test"}),
        ("browser_navigate_tool", {"url": "https://example.com"}),
        ("glob_tool", {"pattern": "*.py"}),
        ("grep_tool", {"pattern": "def", "path": "src/"}),
    ]

    print("Warmup phase...")
    for i in range(warmup_iterations):
        tool_name, args = test_tools[i % len(test_tools)]
        guard.pre_check(tool_name, args)
        guard.record_result(tool_name, args, f"result_{i}")

    guard.reset()
    guard.reset_metrics()

    print(f"Running {test_iterations:,} iterations across 3 runs...")

    run_times = []

    for run in range(3):
        guard.reset()
        guard.reset_metrics()

        start = time.perf_counter()

        for i in range(test_iterations):
            tool_name, args = test_tools[i % len(test_tools)]
            guard.pre_check(tool_name, args)
            guard.record_result(tool_name, args, f"result_{i}")

        elapsed = time.perf_counter() - start
        run_times.append(elapsed)

        per_call_us = (elapsed / test_iterations) * 1_000_000
        throughput = test_iterations / elapsed

        print(f"  Run {run + 1}: {elapsed:.3f}s total, {per_call_us:.2f} us/call, {throughput / 1000:.1f}K calls/sec")

    avg_time = statistics.mean(run_times)
    avg_per_call_us = (avg_time / test_iterations) * 1_000_000
    avg_throughput = test_iterations / avg_time

    return {
        "total_time_sec": avg_time,
        "per_call_us": avg_per_call_us,
        "throughput_calls_per_sec": avg_throughput,
        "iterations": test_iterations,
        "warmup_iterations": warmup_iterations,
        "runs": 3,
    }


def benchmark_detection_modes() -> dict[str, float]:
    """Benchmark individual detection modes."""
    print("\nBenchmarking individual detection modes...")

    guard = LoopGuard()
    iterations = 50_000

    results = {}

    modes = [
        ("repetition", [("file_read", {"path": "/foo"})]),
        ("ping_pong", [("file_read", {"path": "/a"}), ("grep", {"pattern": "x"})]),
        ("no_progress", [("web_search", {"q": "test"})]),
        (
            "divergence",
            [
                ("file_read", {"path": "/a"}),
                ("web_search", {"q": "x"}),
                ("bash", {"cmd": "ls"}),
                ("browser", {"url": "http://x"}),
                ("memory", {"q": "y"}),
            ],
        ),
    ]

    for mode_name, pattern in modes:
        guard.reset()
        guard.reset_metrics()

        start = time.perf_counter()

        for i in range(iterations):
            tool_name, args = pattern[i % len(pattern)]
            guard.pre_check(tool_name, args)
            guard.record_result(tool_name, args, f"result_{i}")

        elapsed = time.perf_counter() - start
        per_call_us = (elapsed / iterations) * 1_000_000

        results[mode_name] = per_call_us
        print(f"  {mode_name}: {per_call_us:.2f} us/call")

    return results


def main() -> None:
    print("=" * 80)
    print("LoopGuard Performance Benchmark")
    print("=" * 80)
    print()

    full_results = benchmark_full_detection()

    print()
    print("=" * 80)
    print("Overall Results (3 runs averaged)")
    print("=" * 80)
    print(f"  Per-call latency:  {full_results['per_call_us']:.2f} us")
    print(f"  Throughput:        {full_results['throughput_calls_per_sec'] / 1000:.1f}K calls/sec")
    print(f"  Total iterations:  {full_results['iterations']:,}")
    print(f"  Warmup iterations: {full_results['warmup_iterations']:,}")
    print(f"  Total runs:        {full_results['runs']}")
    print()

    benchmark_detection_modes()

    print()
    print("=" * 80)
    print("Benchmark Complete")
    print("=" * 80)
    print()
    print("Summary:")
    print(
        f"  Performance: {full_results['per_call_us']:.2f} us/call, "
        f"{full_results['throughput_calls_per_sec'] / 1000:.1f}K calls/sec throughput"
    )
    print(
        f"  Test methodology: {full_results['iterations']:,} iterations + "
        f"{full_results['warmup_iterations']:,} warmup, {full_results['runs']} runs averaged"
    )
    print()


if __name__ == "__main__":
    main()
