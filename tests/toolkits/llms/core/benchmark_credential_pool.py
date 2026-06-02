"""Performance benchmarks for credential pool strategies.

Measures the dispatch latency characteristics of each strategy under
various pool sizes and cooldown conditions.

Run with: pytest benchmark_credential_pool.py --benchmark-only
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.llms.core.credential_pool import CredentialPool


@pytest.fixture(params=[10, 50, 100])
def pool_size(request: pytest.FixtureRequest) -> int:
    """Parameterize pool sizes: 10, 50, 100 keys."""
    return request.param  # type: ignore


@pytest.fixture(params=["round_robin", "fill_first", "least_used", "random"])
def strategy(request: pytest.FixtureRequest) -> str:
    """Parameterize all four strategies."""
    return request.param  # type: ignore


@pytest.fixture
def pool_keys(pool_size: int) -> list[str]:
    """Generate pool keys based on pool_size."""
    return [f"sk-key-{i:03d}" for i in range(pool_size)]


@pytest.fixture
def pool(pool_keys: list[str], strategy: str) -> CredentialPool:
    """Create a credential pool with the given strategy."""
    return CredentialPool(pool_keys, strategy=strategy)


class TestStrategyDispatchLatency:
    """Benchmark credential pool dispatch latency under various conditions."""

    def test_acquire_with_zero_cooldown(
        self, benchmark: pytest.fixture, pool: CredentialPool  # type: ignore
    ) -> None:
        """Benchmark acquire() with no keys in cooldown (best case)."""
        benchmark(pool.acquire)

    def test_acquire_with_50_percent_cooldown(
        self, benchmark: pytest.fixture, pool: CredentialPool  # type: ignore
    ) -> None:
        """Benchmark acquire() with 50% of keys in cooldown."""
        # Put half the keys into cooldown
        total_keys = pool.size
        for _i in range(total_keys // 2):
            key = pool.acquire()
            pool.report_error(key, "rate_limit")

        benchmark(pool.acquire)

    def test_acquire_with_99_percent_cooldown(
        self, benchmark: pytest.fixture, pool: CredentialPool  # type: ignore
    ) -> None:
        """Benchmark acquire() with 99% of keys in cooldown (worst case)."""
        # Put 99% of keys into cooldown
        total_keys = pool.size
        cooled_count = int(total_keys * 0.99)
        for _i in range(cooled_count):
            key = pool.acquire()
            pool.report_error(key, "rate_limit")

        benchmark(pool.acquire)

    def test_acquire_sequential_100_calls(
        self, benchmark: pytest.fixture, pool: CredentialPool  # type: ignore
    ) -> None:
        """Benchmark 100 sequential acquire() calls to test state management overhead."""

        def _sequential_acquires() -> None:
            for _ in range(100):
                pool.acquire()

        benchmark(_sequential_acquires)


class TestReportErrorLatency:
    """Benchmark credential pool error reporting latency."""

    def test_report_error_rate_limit(
        self, benchmark: pytest.fixture, pool: CredentialPool  # type: ignore
    ) -> None:
        """Benchmark report_error() for rate_limit errors."""
        key = pool.acquire()
        benchmark(pool.report_error, key, "rate_limit")

    def test_report_error_auth(
        self, benchmark: pytest.fixture, pool: CredentialPool  # type: ignore
    ) -> None:
        """Benchmark report_error() for auth errors (24h cooldown)."""
        key = pool.acquire()
        benchmark(pool.report_error, key, "auth")


class TestStatsLatency:
    """Benchmark credential pool stats generation latency."""

    def test_stats_with_zero_cooldown(
        self, benchmark: pytest.fixture, pool: CredentialPool  # type: ignore
    ) -> None:
        """Benchmark stats() with no keys in cooldown."""
        benchmark(pool.stats)

    def test_stats_with_50_percent_cooldown(
        self, benchmark: pytest.fixture, pool: CredentialPool  # type: ignore
    ) -> None:
        """Benchmark stats() with 50% of keys in cooldown."""
        total_keys = pool.size
        for _i in range(total_keys // 2):
            key = pool.acquire()
            pool.report_error(key, "rate_limit")

        benchmark(pool.stats)


class TestStrategyComparisonRealWorld:
    """Real-world scenario benchmarks comparing all strategies."""

    def test_high_throughput_scenario(
        self, benchmark: pytest.fixture, pool_keys: list[str], strategy: str
    ) -> None:
        """Simulate high-throughput scenario: 1000 requests with occasional rate limits."""
        pool = CredentialPool(pool_keys, strategy=strategy)

        def _simulate_high_throughput() -> int:
            success_count = 0
            for i in range(1000):
                key = pool.acquire()
                # Simulate 1% rate limit error rate
                if i % 100 == 0:
                    pool.report_error(key, "rate_limit")
                else:
                    success_count += 1
            return success_count

        result = benchmark(_simulate_high_throughput)
        assert result > 0

    def test_primary_backup_scenario_fill_first_only(
        self, benchmark: pytest.fixture, pool_keys: list[str]
    ) -> None:
        """Simulate primary/backup scenario (fill_first strategy only)."""

        def _simulate_primary_backup() -> tuple[int, int]:
            # Create fresh pool for each benchmark run
            pool = CredentialPool(pool_keys, strategy="fill_first")
            primary_uses = 0
            backup_uses = 0

            # Normal operations: primary key used
            for _ in range(100):
                key = pool.acquire()
                if key == pool_keys[0]:
                    primary_uses += 1
                else:
                    backup_uses += 1

            # Primary hits rate limit
            pool.report_error(pool_keys[0], "rate_limit")

            # Backup key used during cooldown
            for _ in range(50):
                key = pool.acquire()
                if key == pool_keys[0]:
                    primary_uses += 1
                else:
                    backup_uses += 1

            return primary_uses, backup_uses

        result = benchmark(_simulate_primary_backup)
        primary_uses, backup_uses = result
        # Verify primary was used initially, then backup after cooldown
        assert primary_uses > 0
        assert backup_uses > 0


class TestLoadBalancingEfficiency:
    """Benchmark load balancing efficiency of LEAST_USED strategy."""

    def test_least_used_load_distribution(
        self, benchmark: pytest.fixture, pool_keys: list[str]
    ) -> None:
        """Verify LEAST_USED distributes load evenly across keys."""
        pool = CredentialPool(pool_keys, strategy="least_used")

        def _test_distribution() -> dict[str, int]:
            call_counts: dict[str, int] = {key: 0 for key in pool_keys}
            for _ in range(1000):
                key = pool.acquire()
                call_counts[key] += 1
            return call_counts

        result = benchmark(_test_distribution)
        # Check distribution variance
        counts = list(result.values())
        avg_count = sum(counts) / len(counts)
        max_deviation = max(abs(c - avg_count) for c in counts)
        # With LEAST_USED, max deviation should be minimal (< 2 for 1000 calls)
        assert max_deviation < 5, f"Load imbalance detected: max deviation {max_deviation}"
