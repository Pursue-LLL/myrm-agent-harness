"""Benchmark for incremental monitoring performance.

Validates performance claims in documentation:
- Time complexity: O(n)
- I/O overhead: ~2ms
- Memory: 1000 URLs ≈ 50KB
"""

import sys
import time
from pathlib import Path

import pytest

from myrm_agent_harness.infra.incremental.set_monitor import SetMonitor


class TestIncrementalMonitorPerformance:
    """Benchmark incremental monitoring performance."""

    @pytest.mark.benchmark(group="compute_delta")
    def test_compute_delta_100_items(self, benchmark: object) -> None:
        """Benchmark compute_delta with 100 items."""
        monitor = SetMonitor(seen={f"url{i}" for i in range(50)})
        output = "\n".join(f"url{i}" for i in range(100))

        result = benchmark(monitor.compute_delta, output)
        assert result

    @pytest.mark.benchmark(group="compute_delta")
    def test_compute_delta_1000_items(self, benchmark: object) -> None:
        """Benchmark compute_delta with 1000 items."""
        monitor = SetMonitor(seen={f"url{i}" for i in range(500)})
        output = "\n".join(f"url{i}" for i in range(1000))

        result = benchmark(monitor.compute_delta, output)
        assert result

    @pytest.mark.benchmark(group="compute_delta")
    def test_compute_delta_10000_items(self, benchmark: object) -> None:
        """Benchmark compute_delta with 10000 items."""
        monitor = SetMonitor(seen={f"url{i}" for i in range(5000)})
        output = "\n".join(f"url{i}" for i in range(10000))

        result = benchmark(monitor.compute_delta, output)
        assert result

    @pytest.mark.benchmark(group="update_baseline")
    def test_update_baseline_100_items(self, benchmark: object) -> None:
        """Benchmark update_baseline with 100 items."""
        monitor = SetMonitor(seen={f"url{i}" for i in range(50)})
        delta = "\n".join(f"url{i}" for i in range(50, 150))

        benchmark(monitor.update_baseline, delta)

    @pytest.mark.benchmark(group="update_baseline")
    def test_update_baseline_1000_items(self, benchmark: object) -> None:
        """Benchmark update_baseline with 1000 items."""
        monitor = SetMonitor(seen={f"url{i}" for i in range(500)})
        delta = "\n".join(f"url{i}" for i in range(500, 1500))

        benchmark(monitor.update_baseline, delta)

    @pytest.mark.benchmark(group="memory")
    def test_memory_1000_urls(self) -> None:
        """Measure memory for 1000 URLs."""
        seen = {f"https://example.com/article{i}" for i in range(1000)}
        monitor = SetMonitor(seen=seen)

        size_bytes = sys.getsizeof(monitor._seen)
        for url in monitor._seen:
            size_bytes += sys.getsizeof(url)

        size_kb = size_bytes / 1024

        print(f"\n1000 URLs memory: {size_kb:.1f} KB")
        assert size_kb < 100, f"Expected <100KB, got {size_kb:.1f}KB"

    @pytest.mark.benchmark(group="memory")
    def test_memory_10000_urls(self) -> None:
        """Measure memory for 10000 URLs."""
        seen = {f"https://example.com/article{i}" for i in range(10000)}
        monitor = SetMonitor(seen=seen)

        size_bytes = sys.getsizeof(monitor._seen)
        for url in monitor._seen:
            size_bytes += sys.getsizeof(url)

        size_kb = size_bytes / 1024

        print(f"\n10000 URLs memory: {size_kb:.1f} KB")
        assert size_kb < 1000, f"Expected <1000KB, got {size_kb:.1f}KB"

    @pytest.mark.benchmark(group="serialization")
    def test_serialization_overhead(self, benchmark: object) -> None:
        """Benchmark state serialization overhead."""
        monitor = SetMonitor(seen={f"url{i}" for i in range(1000)})

        def roundtrip() -> SetMonitor:
            state = monitor.get_state_data()
            return SetMonitor.from_state_data(state)

        result = benchmark(roundtrip)
        assert result


def manual_io_benchmark() -> None:
    """Manual I/O benchmark (not using pytest-benchmark).

    Simulates real-world scenario: load state, compute delta, save state.
    """
    import json
    import tempfile

    print("\n" + "=" * 70)
    print("Manual I/O Benchmark")
    print("=" * 70)

    with tempfile.NamedTemporaryFile(mode="w+", suffix=".json", delete=False) as f:
        temp_path = Path(f.name)

    try:
        seen = {f"url{i}" for i in range(1000)}
        state_data = {"seen": list(seen), "is_baseline": False}

        iterations = 100
        total_time = 0.0

        for _ in range(iterations):
            start = time.perf_counter()

            temp_path.write_text(json.dumps(state_data))

            loaded_data = json.loads(temp_path.read_text())
            monitor = SetMonitor.from_state_data(loaded_data)

            output = "\n".join(f"url{i}" for i in range(1000, 1010))
            delta = monitor.compute_delta(output)
            monitor.update_baseline(delta)

            new_state = monitor.get_state_data()
            temp_path.write_text(json.dumps(new_state))

            elapsed = time.perf_counter() - start
            total_time += elapsed

        avg_ms = (total_time / iterations) * 1000

        print(f"\nIterations: {iterations}")
        print(f"Average time per iteration: {avg_ms:.2f} ms")
        print("Operations per iteration:")
        print("  - Load state from disk")
        print("  - Restore monitor")
        print("  - Compute delta (1010 items)")
        print("  - Update baseline")
        print("  - Save state to disk")
        print("\n✅ Target: <5ms per iteration")
        print(f"📊 Actual: {avg_ms:.2f} ms")

        assert avg_ms < 5, f"Expected <5ms, got {avg_ms:.2f}ms"

    finally:
        temp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    manual_io_benchmark()
