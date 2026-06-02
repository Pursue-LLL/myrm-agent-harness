"""Comprehensive tests for RetryPolicy framework (100% coverage)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.exceptions import (
    BrowserError,
    BrowserLaunchError,
    BrowserNavigationError,
    BrowserNetworkError,
    BrowserTimeoutError,
)
from myrm_agent_harness.toolkits.browser.retry_policy import (
    LaunchRetryPolicy,
    NavigationRetryPolicy,
    NetworkRetryPolicy,
    RetryPolicy,
)

# =============================================================================
# RetryPolicy - Base class
# =============================================================================


class TestRetryPolicy:
    """Test base RetryPolicy class."""

    def test_init_defaults(self) -> None:
        """Test RetryPolicy initialization with defaults."""
        policy = RetryPolicy()

        assert policy.max_attempts == 3
        assert policy.base_delay_ms == 1000
        assert policy.backoff_multiplier == 2.0
        assert policy._cleanup is None

    def test_init_custom(self) -> None:
        """Test RetryPolicy initialization with custom values."""
        cleanup = MagicMock()

        def should_retry(exc: Exception) -> bool:
            return isinstance(exc, ValueError)

        policy = RetryPolicy(
            max_attempts=5,
            base_delay_ms=500,
            backoff_multiplier=1.5,
            should_retry=should_retry,
            cleanup=cleanup,
        )

        assert policy.max_attempts == 5
        assert policy.base_delay_ms == 500
        assert policy.backoff_multiplier == 1.5
        assert policy._cleanup is cleanup
        assert policy._should_retry is should_retry

    def test_default_should_retry_browser_error(self) -> None:
        """Test _default_should_retry returns True for BrowserError."""
        policy = RetryPolicy()

        assert policy._should_retry(BrowserError("test")) is True
        assert policy._should_retry(BrowserNavigationError("test")) is True
        assert policy._should_retry(BrowserNetworkError("test")) is True

    def test_default_should_retry_other_error(self) -> None:
        """Test _default_should_retry returns False for non-BrowserError."""
        policy = RetryPolicy()

        assert policy._should_retry(ValueError("test")) is False
        assert policy._should_retry(RuntimeError("test")) is False

    def test_calculate_delay_exponential(self) -> None:
        """Test _calculate_delay with exponential backoff."""
        policy = RetryPolicy(base_delay_ms=1000, backoff_multiplier=2.0)

        assert policy._calculate_delay(0) == 1.0
        assert policy._calculate_delay(1) == 2.0
        assert policy._calculate_delay(2) == 4.0
        assert policy._calculate_delay(3) == 8.0

    def test_calculate_delay_fixed(self) -> None:
        """Test _calculate_delay with fixed delay (multiplier=1.0)."""
        policy = RetryPolicy(base_delay_ms=2000, backoff_multiplier=1.0)

        assert policy._calculate_delay(0) == 2.0
        assert policy._calculate_delay(1) == 2.0
        assert policy._calculate_delay(2) == 2.0

    @pytest.mark.asyncio
    async def test_execute_success_first_attempt(self) -> None:
        """Test execute succeeds on first attempt."""
        policy = RetryPolicy()

        async def func() -> str:
            return "success"

        result = await policy.execute(func)

        assert result == "success"

    @pytest.mark.asyncio
    async def test_execute_success_after_retry(self) -> None:
        """Test execute succeeds after one retry."""
        policy = RetryPolicy(max_attempts=3, base_delay_ms=10)

        attempts = 0

        async def func() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise BrowserError("First attempt fails")
            return "success"

        result = await policy.execute(func)

        assert result == "success"
        assert attempts == 2

    @pytest.mark.asyncio
    async def test_execute_all_attempts_fail(self) -> None:
        """Test execute raises after all attempts exhausted."""
        policy = RetryPolicy(max_attempts=3, base_delay_ms=10)

        async def func() -> str:
            raise BrowserError("Always fails")

        with pytest.raises(BrowserError, match="Always fails"):
            await policy.execute(func)

    @pytest.mark.asyncio
    async def test_execute_non_retryable_exception(self) -> None:
        """Test execute raises immediately for non-retryable exception."""
        policy = RetryPolicy(max_attempts=3)

        attempts = 0

        async def func() -> str:
            nonlocal attempts
            attempts += 1
            raise ValueError("Non-retryable")

        with pytest.raises(ValueError, match="Non-retryable"):
            await policy.execute(func)

        assert attempts == 1

    @pytest.mark.asyncio
    async def test_execute_with_cleanup_async(self) -> None:
        """Test execute calls async cleanup before retry."""
        cleanup_calls = []

        async def cleanup() -> None:
            cleanup_calls.append(1)

        policy = RetryPolicy(max_attempts=3, base_delay_ms=10, cleanup=cleanup)

        attempts = 0

        async def func() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise BrowserError("First attempt fails")
            return "success"

        result = await policy.execute(func)

        assert result == "success"
        assert len(cleanup_calls) == 1

    @pytest.mark.asyncio
    async def test_execute_with_cleanup_sync(self) -> None:
        """Test execute calls sync cleanup before retry."""
        cleanup_calls = []

        def cleanup() -> None:
            cleanup_calls.append(1)

        policy = RetryPolicy(max_attempts=3, base_delay_ms=10, cleanup=cleanup)

        attempts = 0

        async def func() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise BrowserError("First attempt fails")
            return "success"

        result = await policy.execute(func)

        assert result == "success"
        assert len(cleanup_calls) == 1

    @pytest.mark.asyncio
    async def test_execute_cleanup_failure_does_not_break_retry(self) -> None:
        """Test execute continues retry even if cleanup fails."""

        async def cleanup() -> None:
            raise RuntimeError("Cleanup failed")

        policy = RetryPolicy(max_attempts=3, base_delay_ms=10, cleanup=cleanup)

        attempts = 0

        async def func() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise BrowserError("First attempt fails")
            return "success"

        result = await policy.execute(func)

        assert result == "success"
        assert attempts == 2

    @pytest.mark.asyncio
    async def test_execute_sync_function(self) -> None:
        """Test execute works with sync functions."""
        policy = RetryPolicy()

        def func() -> str:
            return "success"

        result = await policy.execute(func)

        assert result == "success"

    @pytest.mark.asyncio
    async def test_execute_sync_function_with_retry(self) -> None:
        """Test execute retries sync functions."""
        policy = RetryPolicy(max_attempts=3, base_delay_ms=10)

        attempts = 0

        def func() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise BrowserError("First attempt fails")
            return "success"

        result = await policy.execute(func)

        assert result == "success"
        assert attempts == 2


# =============================================================================
# NavigationRetryPolicy
# =============================================================================


class TestNavigationRetryPolicy:
    """Test NavigationRetryPolicy."""

    def test_init_defaults(self) -> None:
        """Test NavigationRetryPolicy initialization."""
        policy = NavigationRetryPolicy()

        assert policy.max_attempts == 3
        assert policy.base_delay_ms == 1000
        assert policy.backoff_multiplier == 2.0

    def test_init_with_cleanup(self) -> None:
        """Test NavigationRetryPolicy with cleanup."""
        cleanup = MagicMock()
        policy = NavigationRetryPolicy(cleanup=cleanup)

        assert policy._cleanup is cleanup

    @pytest.mark.asyncio
    async def test_retries_navigation_error(self) -> None:
        """Test retries BrowserNavigationError."""
        policy = NavigationRetryPolicy()

        attempts = 0

        async def func() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise BrowserNavigationError("Navigation failed")
            return "success"

        result = await policy.execute(func)

        assert result == "success"
        assert attempts == 2

    @pytest.mark.asyncio
    async def test_retries_timeout_error(self) -> None:
        """Test retries BrowserTimeoutError."""
        policy = NavigationRetryPolicy()

        attempts = 0

        async def func() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise BrowserTimeoutError("Timeout")
            return "success"

        result = await policy.execute(func)

        assert result == "success"
        assert attempts == 2

    @pytest.mark.asyncio
    async def test_retries_network_error(self) -> None:
        """Test retries BrowserNetworkError."""
        policy = NavigationRetryPolicy()

        attempts = 0

        async def func() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise BrowserNetworkError("Network error")
            return "success"

        result = await policy.execute(func)

        assert result == "success"
        assert attempts == 2

    @pytest.mark.asyncio
    async def test_no_retry_for_other_errors(self) -> None:
        """Test does not retry non-navigation errors."""
        policy = NavigationRetryPolicy()

        attempts = 0

        async def func() -> str:
            nonlocal attempts
            attempts += 1
            raise ValueError("Not a navigation error")

        with pytest.raises(ValueError):
            await policy.execute(func)

        assert attempts == 1


# =============================================================================
# LaunchRetryPolicy
# =============================================================================


class TestLaunchRetryPolicy:
    """Test LaunchRetryPolicy."""

    def test_init_defaults(self) -> None:
        """Test LaunchRetryPolicy initialization."""
        policy = LaunchRetryPolicy()

        assert policy.max_attempts == 2
        assert policy.base_delay_ms == 2000
        assert policy.backoff_multiplier == 1.0

    def test_init_with_cleanup(self) -> None:
        """Test LaunchRetryPolicy with cleanup."""
        cleanup = MagicMock()
        policy = LaunchRetryPolicy(cleanup=cleanup)

        assert policy._cleanup is cleanup

    @pytest.mark.asyncio
    async def test_retries_launch_error(self) -> None:
        """Test retries BrowserLaunchError."""
        policy = LaunchRetryPolicy()

        attempts = 0

        async def func() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise BrowserLaunchError("Launch failed")
            return "success"

        result = await policy.execute(func)

        assert result == "success"
        assert attempts == 2

    @pytest.mark.asyncio
    async def test_no_retry_for_other_errors(self) -> None:
        """Test does not retry non-launch errors."""
        policy = LaunchRetryPolicy()

        attempts = 0

        async def func() -> str:
            nonlocal attempts
            attempts += 1
            raise BrowserNavigationError("Not a launch error")

        with pytest.raises(BrowserNavigationError):
            await policy.execute(func)

        assert attempts == 1

    @pytest.mark.asyncio
    async def test_fixed_delay(self) -> None:
        """Test fixed delay (backoff_multiplier=1.0)."""
        policy = LaunchRetryPolicy()

        assert policy._calculate_delay(0) == 2.0
        assert policy._calculate_delay(1) == 2.0


# =============================================================================
# NetworkRetryPolicy
# =============================================================================


class TestNetworkRetryPolicy:
    """Test NetworkRetryPolicy."""

    def test_init_defaults(self) -> None:
        """Test NetworkRetryPolicy initialization."""
        policy = NetworkRetryPolicy()

        assert policy.max_attempts == 5
        assert policy.base_delay_ms == 1000
        assert policy.backoff_multiplier == 2.0

    def test_init_with_cleanup(self) -> None:
        """Test NetworkRetryPolicy with cleanup."""
        cleanup = MagicMock()
        policy = NetworkRetryPolicy(cleanup=cleanup)

        assert policy._cleanup is cleanup

    @pytest.mark.asyncio
    async def test_retries_network_error(self) -> None:
        """Test retries BrowserNetworkError."""
        policy = NetworkRetryPolicy()

        attempts = 0

        async def func() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise BrowserNetworkError("Network error")
            return "success"

        result = await policy.execute(func)

        assert result == "success"
        assert attempts == 2

    @pytest.mark.asyncio
    async def test_retries_timeout_error(self) -> None:
        """Test retries BrowserTimeoutError."""
        policy = NetworkRetryPolicy()

        attempts = 0

        async def func() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise BrowserTimeoutError("Timeout")
            return "success"

        result = await policy.execute(func)

        assert result == "success"
        assert attempts == 2

    @pytest.mark.asyncio
    async def test_no_retry_for_other_errors(self) -> None:
        """Test does not retry non-network errors."""
        policy = NetworkRetryPolicy()

        attempts = 0

        async def func() -> str:
            nonlocal attempts
            attempts += 1
            raise BrowserLaunchError("Not a network error")

        with pytest.raises(BrowserLaunchError):
            await policy.execute(func)

        assert attempts == 1

    @pytest.mark.asyncio
    async def test_max_5_attempts(self) -> None:
        """Test NetworkRetryPolicy allows 5 attempts."""
        policy = NetworkRetryPolicy()

        attempts = 0

        async def func() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 5:
                raise BrowserNetworkError(f"Attempt {attempts}")
            return "success"

        result = await policy.execute(func)

        assert result == "success"
        assert attempts == 5


# =============================================================================
# Edge cases and error handling
# =============================================================================


@pytest.mark.asyncio
async def test_execute_with_args_and_kwargs() -> None:
    """Test execute passes args and kwargs correctly."""
    policy = RetryPolicy()

    async def func(a: int, b: int, c: int = 0) -> int:
        return a + b + c

    result = await policy.execute(func, 1, 2, c=3)

    assert result == 6


@pytest.mark.asyncio
async def test_execute_preserves_exception_chain() -> None:
    """Test execute preserves exception information."""
    policy = RetryPolicy(max_attempts=2, base_delay_ms=10)

    async def func() -> str:
        raise BrowserNavigationError("Navigation failed")

    with pytest.raises(BrowserNavigationError, match="Navigation failed"):
        await policy.execute(func)


@pytest.mark.asyncio
async def test_custom_should_retry_function() -> None:
    """Test custom should_retry function."""

    def should_retry(exc: Exception) -> bool:
        return isinstance(exc, ValueError)

    policy = RetryPolicy(max_attempts=3, base_delay_ms=10, should_retry=should_retry)

    attempts = 0

    async def func() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ValueError("Retryable ValueError")
        return "success"

    result = await policy.execute(func)

    assert result == "success"
    assert attempts == 2


@pytest.mark.asyncio
async def test_cleanup_called_between_retries() -> None:
    """Test cleanup is called between retries."""
    cleanup_calls = []

    async def cleanup() -> None:
        cleanup_calls.append(1)

    policy = RetryPolicy(max_attempts=3, base_delay_ms=10, cleanup=cleanup)

    attempts = 0

    async def func() -> str:
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise BrowserError(f"Attempt {attempts}")
        return "success"

    result = await policy.execute(func)

    assert result == "success"
    assert len(cleanup_calls) == 2


@pytest.mark.asyncio
async def test_cleanup_not_called_on_success() -> None:
    """Test cleanup is not called if first attempt succeeds."""
    cleanup_calls = []

    async def cleanup() -> None:
        cleanup_calls.append(1)

    policy = RetryPolicy(max_attempts=3, cleanup=cleanup)

    async def func() -> str:
        return "success"

    result = await policy.execute(func)

    assert result == "success"
    assert len(cleanup_calls) == 0


@pytest.mark.asyncio
async def test_delay_timing() -> None:
    """Test actual delay timing."""
    policy = RetryPolicy(max_attempts=3, base_delay_ms=50, backoff_multiplier=2.0)

    attempts = 0
    start_times = []

    async def func() -> str:
        nonlocal attempts
        start_times.append(asyncio.get_event_loop().time())
        attempts += 1
        if attempts == 1:
            raise BrowserError("First attempt")
        return "success"

    result = await policy.execute(func)

    assert result == "success"
    assert len(start_times) == 2

    elapsed = start_times[1] - start_times[0]
    assert 0.04 < elapsed < 0.1


@pytest.mark.asyncio
async def test_execute_with_exception_filtering() -> None:
    """Test execute with custom exception filter."""

    def should_retry(exc: Exception) -> bool:
        return "retryable" in str(exc).lower()

    policy = RetryPolicy(max_attempts=3, base_delay_ms=10, should_retry=should_retry)

    attempts = 0

    async def func() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise BrowserError("Retryable error")
        return "success"

    result = await policy.execute(func)

    assert result == "success"
    assert attempts == 2


@pytest.mark.asyncio
async def test_last_exception_raised_if_no_attempts() -> None:
    """Test last_exception is raised if somehow no attempts were made."""
    policy = RetryPolicy(max_attempts=0, base_delay_ms=10)

    async def func() -> str:
        return "should not be called"

    with pytest.raises(RuntimeError, match="failed with unknown error"):
        await policy.execute(func)


@pytest.mark.asyncio
async def test_last_exception_raised_after_all_retries_fail() -> None:
    """测试所有重试失败后抛出last_exception（覆盖line 160）"""
    policy = RetryPolicy(max_attempts=2, base_delay_ms=10)

    async def func() -> str:
        raise BrowserError("Persistent failure")

    with pytest.raises(BrowserError, match="Persistent failure"):
        await policy.execute(func)
