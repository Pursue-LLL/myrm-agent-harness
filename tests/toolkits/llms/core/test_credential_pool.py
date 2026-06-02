"""Tests for CredentialPool — multi-key round-robin with error-aware cooldown."""

from __future__ import annotations

import time

import pytest

from myrm_agent_harness.toolkits.llms.core.credential_pool import CredentialPool, CredentialPoolStrategy


class TestCredentialPoolInit:
    def test_single_key(self) -> None:
        pool = CredentialPool(["sk-key1"])
        assert pool.size == 1
        assert pool.is_single_key
        assert pool.strategy == CredentialPoolStrategy.ROUND_ROBIN

    def test_multiple_keys(self) -> None:
        pool = CredentialPool(["sk-key1", "sk-key2", "sk-key3"])
        assert pool.size == 3
        assert not pool.is_single_key

    def test_deduplicates_keys(self) -> None:
        pool = CredentialPool(["sk-key1", "sk-key2", "sk-key1", "sk-key3", "sk-key2"])
        assert pool.size == 3

    def test_empty_keys_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one key"):
            CredentialPool([])

    def test_cooldown_floor(self) -> None:
        pool = CredentialPool(["sk-key1"], cooldown_s=0.01)
        assert pool._cooldown_s == 1.0

    def test_strategy_reads_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYRM_LLM_CREDENTIAL_POOL_STRATEGY", "least_used")
        pool = CredentialPool(["sk-key1", "sk-key2"])
        assert pool.strategy == CredentialPoolStrategy.LEAST_USED

    def test_invalid_strategy_for_multi_key_pool_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported credential pool strategy"):
            CredentialPool(["sk-key1", "sk-key2"], strategy="does-not-exist")


class TestCredentialPoolRoundRobin:
    def test_round_robin_order(self) -> None:
        pool = CredentialPool(["a", "b", "c"])
        assert pool.acquire() == "a"
        assert pool.acquire() == "b"
        assert pool.acquire() == "c"
        assert pool.acquire() == "a"

    def test_single_key_always_same(self) -> None:
        pool = CredentialPool(["only"])
        for _ in range(5):
            assert pool.acquire() == "only"


class TestCredentialPoolStrategies:
    def test_fill_first_prefers_primary_until_cooldown(self) -> None:
        pool = CredentialPool(["a", "b", "c"], strategy="fill-first")
        assert pool.acquire() == "a"
        assert pool.acquire() == "a"
        pool.report_error("a", "rate_limit", cooldown_hint_s=0.1)
        assert pool.acquire() == "b"
        assert pool.acquire() == "b"
        time.sleep(0.2)
        assert pool.acquire() == "a"

    def test_least_used_balances_calls(self) -> None:
        pool = CredentialPool(["a", "b", "c"], strategy=CredentialPoolStrategy.LEAST_USED)
        assert [pool.acquire() for _ in range(6)] == ["a", "b", "c", "a", "b", "c"]
        stats = pool.stats()
        assert stats["strategy"] == "least_used"
        assert stats["total_calls"] == 6

    def test_random_strategy_uses_available_pool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pool = CredentialPool(["a", "b", "c"], strategy=CredentialPoolStrategy.RANDOM)
        monkeypatch.setattr(
            "myrm_agent_harness.toolkits.llms.core.credential_pool.random.choice",
            lambda slots: slots[-1],
        )
        assert pool.acquire() == "c"
        pool.report_error("c", "rate_limit", cooldown_hint_s=0.1)
        assert pool.acquire() == "b"


class TestCredentialPoolCooldown:
    def test_skip_cooled_key(self) -> None:
        pool = CredentialPool(["a", "b", "c"], cooldown_s=60)
        pool.acquire()  # "a"
        pool.report_error("a", "rate_limit")
        assert pool.acquire() == "b"
        assert pool.acquire() == "c"
        assert pool.acquire() == "b"

    def test_all_cooled_returns_earliest(self) -> None:
        pool = CredentialPool(["a", "b"], cooldown_s=60)
        pool.report_error("a", "rate_limit")
        pool.report_error("b", "rate_limit")
        key = pool.acquire()
        assert key in ("a", "b")

    def test_available_count(self) -> None:
        pool = CredentialPool(["a", "b", "c"], cooldown_s=60)
        assert pool.available_count() == 3
        pool.report_error("a", "rate_limit")
        assert pool.available_count() == 2
        pool.report_error("b", "rate_limit")
        assert pool.available_count() == 1

    def test_cooldown_expires(self) -> None:
        pool = CredentialPool(["a", "b"], cooldown_s=1.0)
        pool.acquire()  # "a"
        pool.report_error("a", "rate_limit")
        assert pool.available_count() == 1
        # Directly expire the cooldown to avoid timing flakiness in parallel tests
        pool._slots[0].cooldown_until = time.monotonic() - 0.1
        assert pool.available_count() == 2

    def test_report_error_never_shortens_existing_cooldown(self) -> None:
        pool = CredentialPool(["a", "b"])
        pool.report_error("a", "auth")
        auth_cooldown_until = pool._slots[0].cooldown_until
        pool.report_error("a", "rate_limit", cooldown_hint_s=1.0)
        assert pool._slots[0].cooldown_until == auth_cooldown_until


class TestCredentialPoolStats:
    def test_stats_structure(self) -> None:
        pool = CredentialPool(["a", "b"])
        pool.acquire()
        pool.acquire()
        pool.report_error("a", "rate_limit")
        stats = pool.stats()

        assert stats["strategy"] == "round_robin"
        assert stats["total_keys"] == 2
        assert stats["total_calls"] == 2
        assert stats["total_rate_limits"] == 1
        assert len(stats["keys"]) == 2  # type: ignore[arg-type]

        key_a = next(k for k in stats["keys"] if k["suffix"] == "a")  # type: ignore[union-attr]
        assert key_a["calls"] == 1
        assert key_a["rate_limits"] == 1
        assert key_a["in_cooldown"] is True

    def test_call_count_increments(self) -> None:
        pool = CredentialPool(["x"])
        for _ in range(10):
            pool.acquire()
        assert pool.stats()["total_calls"] == 10

    def test_report_nonexistent_key_no_crash(self) -> None:
        pool = CredentialPool(["a"])
        pool.report_error("nonexistent", "rate_limit")
        assert pool.stats()["total_rate_limits"] == 0

    def test_stats_includes_error_count(self) -> None:
        pool = CredentialPool(["a", "b"])
        pool.report_error("a", "auth")
        stats = pool.stats()
        assert stats["total_errors"] == 1
        key_a = next(k for k in stats["keys"] if k["suffix"] == "a")  # type: ignore[union-attr]
        assert key_a["errors"] == 1
        assert key_a["rate_limits"] == 0


class TestCredentialPoolReportError:
    def test_rate_limit_default_cooldown(self) -> None:
        pool = CredentialPool(["a", "b"], cooldown_s=60)
        pool.report_error("a", "rate_limit")
        assert pool.available_count() == 1

    def test_rate_limit_with_hint(self) -> None:
        pool = CredentialPool(["a", "b"], cooldown_s=60)
        pool.report_error("a", "rate_limit", cooldown_hint_s=3.0)
        assert pool.available_count() == 1
        import time
        time.sleep(3.1)
        assert pool.available_count() == 2

    def test_auth_error_long_cooldown(self) -> None:
        pool = CredentialPool(["a", "b"], cooldown_s=1)
        pool.report_error("a", "auth")
        assert pool.available_count() == 1
        import time
        time.sleep(1.1)
        assert pool.available_count() == 1  # still cooled down (24h cooldown)

    def test_billing_error_long_cooldown(self) -> None:
        pool = CredentialPool(["a", "b"], cooldown_s=1)
        pool.report_error("a", "billing")
        assert pool.available_count() == 1
        import time
        time.sleep(1.1)
        assert pool.available_count() == 1  # still cooled down (24h cooldown)

    def test_rate_limit_increments_rate_limit_count(self) -> None:
        pool = CredentialPool(["a"])
        pool.report_error("a", "rate_limit")
        stats = pool.stats()
        assert stats["total_rate_limits"] == 1
        assert stats["total_errors"] == 1

    def test_auth_does_not_increment_rate_limit_count(self) -> None:
        pool = CredentialPool(["a"])
        pool.report_error("a", "auth")
        stats = pool.stats()
        assert stats["total_rate_limits"] == 0
        assert stats["total_errors"] == 1

    def test_cooldown_hint_ignored_for_auth(self) -> None:
        pool = CredentialPool(["a", "b"], cooldown_s=1)
        pool.report_error("a", "auth", cooldown_hint_s=0.5)
        import time
        time.sleep(0.6)
        assert pool.available_count() == 1  # auth ignores hint, uses 24h


class TestCredentialPoolExponentialBackoff:
    """Tests for exponential backoff with jitter on consecutive rate limits."""

    def test_consecutive_rate_limits_increase_cooldown(self) -> None:
        pool = CredentialPool(["a"], cooldown_s=10)
        pool.report_error("a", "rate_limit")
        first_cooldown = pool._slots[0].cooldown_until
        # Reset time reference
        pool._slots[0].cooldown_until = 0.0

        pool.report_error("a", "rate_limit")
        second_cooldown = pool._slots[0].cooldown_until
        # Second cooldown should be longer (exponential backoff)
        assert second_cooldown > first_cooldown

    def test_report_success_resets_consecutive_counter(self) -> None:
        pool = CredentialPool(["a"], cooldown_s=10)
        pool.report_error("a", "rate_limit")
        pool.report_error("a", "rate_limit")
        assert pool._slots[0].consecutive_rate_limit_count == 2

        pool.report_success("a")
        assert pool._slots[0].consecutive_rate_limit_count == 0

    def test_consecutive_counter_tracks_per_key(self) -> None:
        pool = CredentialPool(["a", "b"], cooldown_s=10)
        pool.report_error("a", "rate_limit")
        pool.report_error("a", "rate_limit")
        pool.report_error("b", "rate_limit")

        assert pool._slots[0].consecutive_rate_limit_count == 2
        assert pool._slots[1].consecutive_rate_limit_count == 1

    def test_auth_resets_consecutive_rate_limit_counter(self) -> None:
        pool = CredentialPool(["a"], cooldown_s=10)
        pool.report_error("a", "rate_limit")
        pool.report_error("a", "rate_limit")
        assert pool._slots[0].consecutive_rate_limit_count == 2

        pool.report_error("a", "auth")
        assert pool._slots[0].consecutive_rate_limit_count == 0

    def test_jitter_varies_cooldown(self) -> None:
        """Verify that two identical rate limits produce different cooldowns due to jitter."""
        import time

        cooldowns: list[float] = []
        for _ in range(10):
            pool = CredentialPool(["a"], cooldown_s=60)
            now = time.monotonic()
            pool.report_error("a", "rate_limit")
            cooldowns.append(pool._slots[0].cooldown_until - now)
        # With ±15% jitter, not all cooldowns should be identical
        assert len(set(cooldowns)) > 1


class TestCredentialPoolStatsGlobal:
    """Tests for stats() global metrics."""

    def test_max_consecutive_rate_limits_zero_initially(self) -> None:
        pool = CredentialPool(["a", "b"])
        assert pool.stats()["max_consecutive_rate_limits"] == 0

    def test_max_consecutive_rate_limits_tracks_max(self) -> None:
        pool = CredentialPool(["a", "b"])
        pool.report_error("a", "rate_limit")
        pool.report_error("a", "rate_limit")
        pool.report_error("a", "rate_limit")
        pool.report_error("b", "rate_limit")
        assert pool.stats()["max_consecutive_rate_limits"] == 3

    def test_max_consecutive_rate_limits_resets_on_success(self) -> None:
        pool = CredentialPool(["a"])
        pool.report_error("a", "rate_limit")
        pool.report_error("a", "rate_limit")
        assert pool.stats()["max_consecutive_rate_limits"] == 2

        pool.report_success("a")
        assert pool.stats()["max_consecutive_rate_limits"] == 0
