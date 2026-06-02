"""Tests for agent/security/rate_limiter.py — rate limiting for brute-force protection."""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.agent.security.rate_limiter import MemoryRateLimiter, RateLimitConfig


class TestMemoryRateLimiter:
    """Tests for MemoryRateLimiter."""

    @pytest.mark.asyncio
    async def test_opt1_per_key_rate_limit(self) -> None:
        """OPT-1: Per-IP限流 — 5次/60秒."""
        limiter = MemoryRateLimiter(RateLimitConfig(max_attempts_per_key=5, max_attempts_global=100, window_seconds=60))

        # First 5 attempts should pass
        for i in range(5):
            result = await limiter.check("ip:192.168.1.1")
            assert result.allowed, f"Attempt {i + 1} should be allowed"

        # 6th attempt should fail
        result = await limiter.check("ip:192.168.1.1")
        assert not result.allowed
        assert result.retry_after_seconds is not None
        assert result.retry_after_seconds > 0

    @pytest.mark.asyncio
    async def test_opt2_global_rate_limit(self) -> None:
        """OPT-2: 全局限流 — 100次/60秒（防IP伪造）."""
        limiter = MemoryRateLimiter(
            RateLimitConfig(
                max_attempts_per_key=5,
                max_attempts_global=10,  # Small global limit for testing
                window_seconds=60,
            )
        )

        # Use different IPs, but all should be counted globally
        for i in range(10):
            result = await limiter.check(f"ip:192.168.1.{i}")
            assert result.allowed, f"Global attempt {i + 1} should be allowed"

        # 11th attempt (different IP) should fail due to global limit
        result = await limiter.check("ip:192.168.1.99")
        assert not result.allowed
        assert result.retry_after_seconds is not None

    @pytest.mark.asyncio
    async def test_opt3_sliding_window_reset(self) -> None:
        """OPT-3: 滑动窗口 — 窗口过期后重置."""
        limiter = MemoryRateLimiter(
            RateLimitConfig(
                max_attempts_per_key=2,
                max_attempts_global=100,
                window_seconds=1,  # 1 second window for fast testing
            )
        )

        # First 2 attempts should pass
        result1 = await limiter.check("ip:192.168.1.1")
        result2 = await limiter.check("ip:192.168.1.1")
        assert result1.allowed
        assert result2.allowed

        # 3rd attempt should fail
        result3 = await limiter.check("ip:192.168.1.1")
        assert not result3.allowed

        # Wait for window to expire
        await asyncio.sleep(1.1)

        # After window expires, should be allowed again
        result4 = await limiter.check("ip:192.168.1.1")
        assert result4.allowed

    @pytest.mark.asyncio
    async def test_different_keys_independent(self) -> None:
        """Different keys should have independent rate limits."""
        limiter = MemoryRateLimiter(RateLimitConfig(max_attempts_per_key=2, max_attempts_global=100, window_seconds=60))

        # IP1: 2 attempts (max)
        await limiter.check("ip:192.168.1.1")
        await limiter.check("ip:192.168.1.1")

        # IP2: should still be allowed
        result = await limiter.check("ip:192.168.1.2")
        assert result.allowed

    @pytest.mark.asyncio
    async def test_opt3_cleanup_stale_entries(self) -> None:
        """OPT-3: 定期清理 — 防止内存泄漏."""
        limiter = MemoryRateLimiter(
            RateLimitConfig(
                max_attempts_per_key=5,
                max_attempts_global=100,
                window_seconds=1,  # 1 second window
            )
        )

        # Create some entries
        await limiter.check("ip:192.168.1.1")
        await limiter.check("ip:192.168.1.2")
        await limiter.check("ip:192.168.1.3")

        # Before cleanup
        assert len(limiter._entries) == 3

        # Wait for entries to become stale (2x window)
        await asyncio.sleep(2.1)

        # Run cleanup
        await limiter._cleanup_stale_entries()

        # After cleanup, stale entries should be removed
        assert len(limiter._entries) == 0

    @pytest.mark.asyncio
    async def test_cleanup_task_lifecycle(self) -> None:
        """Test cleanup task start/stop lifecycle."""
        limiter = MemoryRateLimiter(
            RateLimitConfig(
                max_attempts_per_key=5,
                max_attempts_global=100,
                window_seconds=60,
                cleanup_interval_seconds=1,  # Fast cleanup for testing
            )
        )

        # Start cleanup task
        await limiter.start_cleanup_task()
        assert limiter._cleanup_task is not None

        # Wait a bit to let cleanup run
        await asyncio.sleep(0.1)

        # Stop cleanup task
        await limiter.stop_cleanup_task()
        assert limiter._cleanup_task is None

    @pytest.mark.asyncio
    async def test_retry_after_seconds_accurate(self) -> None:
        """Test retry_after_seconds is accurate."""
        limiter = MemoryRateLimiter(RateLimitConfig(max_attempts_per_key=1, max_attempts_global=100, window_seconds=60))

        # First attempt passes
        result1 = await limiter.check("ip:192.168.1.1")
        assert result1.allowed

        # Second attempt fails
        result2 = await limiter.check("ip:192.168.1.1")
        assert not result2.allowed
        assert result2.retry_after_seconds is not None
        # Should be close to 60 seconds (within 60s window)
        assert 55 <= result2.retry_after_seconds <= 60

    @pytest.mark.asyncio
    async def test_opt9_concurrent_access_no_race_condition(self) -> None:
        """OPT-9: Concurrent access with asyncio.Lock — no race condition."""
        limiter = MemoryRateLimiter(
            RateLimitConfig(max_attempts_per_key=10, max_attempts_global=100, window_seconds=60)
        )

        # Simulate 50 concurrent requests to the same IP
        tasks = [limiter.check("ip:192.168.1.1") for _ in range(50)]
        results = await asyncio.gather(*tasks)

        # Count allowed and denied
        allowed_count = sum(1 for r in results if r.allowed)
        denied_count = sum(1 for r in results if not r.allowed)

        # Should allow exactly 10 (max_attempts_per_key), deny 40
        assert allowed_count == 10
        assert denied_count == 40

    @pytest.mark.asyncio
    async def test_opt9_concurrent_global_limit_no_race_condition(self) -> None:
        """OPT-9: Concurrent global limit — no race condition."""
        limiter = MemoryRateLimiter(
            RateLimitConfig(
                max_attempts_per_key=100,
                max_attempts_global=10,  # Small global limit
                window_seconds=60,
            )
        )

        # Simulate 50 concurrent requests from different IPs
        tasks = [limiter.check(f"ip:192.168.1.{i}") for i in range(50)]
        results = await asyncio.gather(*tasks)

        # Count allowed and denied
        allowed_count = sum(1 for r in results if r.allowed)
        denied_count = sum(1 for r in results if not r.allowed)

        # Should allow exactly 10 (max_attempts_global), deny 40
        assert allowed_count == 10
        assert denied_count == 40
