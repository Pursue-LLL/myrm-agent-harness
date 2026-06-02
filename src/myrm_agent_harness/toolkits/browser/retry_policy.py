"""Retry policy framework for browser operations.

Provides customizable retry strategies with exponential backoff, cleanup
hooks, and exception filtering. Zero external dependencies (no tenacity).

Architecture:
    RetryPolicy (base class)
    ├── NavigationRetryPolicy
    ├── LaunchRetryPolicy
    └── NetworkRetryPolicy

Usage:
    policy = NavigationRetryPolicy()
    result = await policy.execute(page.goto, "https://example.com")


[INPUT]

[OUTPUT]
- Result of successful function execution
- Exception: If all retries exhausted

[POS]
Retry policy framework. Zero external dependencies. Async-first design.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from .exceptions import (
    BrowserError,
    BrowserLaunchError,
    BrowserNavigationError,
    BrowserNetworkError,
    BrowserTimeoutError,
)

logger = logging.getLogger(__name__)


class RetryPolicy:
    """Base retry policy with configurable strategy.

    Features:
    - Exponential backoff with configurable multiplier
    - Exception filtering (only retry specific exceptions)
    - Cleanup hooks (execute before each retry)
    - Detailed logging with attempt counts
    """

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay_ms: int = 1000,
        backoff_multiplier: float = 2.0,
        should_retry: Callable[[Exception], bool] | None = None,
        cleanup: Callable[[], Any] | None = None,
    ) -> None:
        """Initialize retry policy.

        Args:
            max_attempts: Maximum number of attempts (default 3)
            base_delay_ms: Base delay in milliseconds (default 1000)
            backoff_multiplier: Delay multiplier for exponential backoff (default 2.0)
            should_retry: Filter function to determine if exception should trigger retry
            cleanup: Cleanup function to execute before each retry (async or sync)
        """
        self.max_attempts = max_attempts
        self.base_delay_ms = base_delay_ms
        self.backoff_multiplier = backoff_multiplier
        self._should_retry = should_retry or self._default_should_retry
        self._cleanup = cleanup

    def _default_should_retry(self, exc: Exception) -> bool:
        """Default retry filter: retry all BrowserError subclasses."""
        return isinstance(exc, BrowserError)

    def _calculate_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt (exponential backoff).

        Args:
            attempt: Zero-based attempt number (0 = first retry)

        Returns:
            Delay in seconds
        """
        delay_ms = self.base_delay_ms * (self.backoff_multiplier**attempt)
        return delay_ms / 1000.0

    async def execute(
        self,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute function with retry policy.

        Args:
            func: Function to execute (can be async or sync)
            *args: Positional arguments to pass to func
            **kwargs: Keyword arguments to pass to func

        Returns:
            Result of successful function execution

        Raises:
            Exception: If all retries exhausted or non-retryable exception
        """
        last_exception: Exception | None = None

        for attempt in range(self.max_attempts):
            try:
                if asyncio.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                return func(*args, **kwargs)

            except Exception as exc:
                last_exception = exc

                if not self._should_retry(exc):
                    logger.warning(f"{func.__name__} failed with non-retryable error: {exc}")
                    raise

                if attempt == self.max_attempts - 1:
                    logger.warning(f"{func.__name__} failed after {self.max_attempts} attempts: {exc}")
                    raise

                delay = self._calculate_delay(attempt)
                logger.warning(
                    f"{func.__name__} failed (attempt {attempt + 1}/{self.max_attempts}): {exc}. "
                    f"Retrying in {delay:.1f}s..."
                )

                if self._cleanup:
                    try:
                        if asyncio.iscoroutinefunction(self._cleanup):
                            await self._cleanup()
                        else:
                            self._cleanup()
                    except Exception as cleanup_exc:
                        logger.warning(f"Cleanup failed: {cleanup_exc}")

                await asyncio.sleep(delay)

        if last_exception:
            raise last_exception  # pragma: no cover
        raise RuntimeError(f"{func.__name__} failed with unknown error")


class NavigationRetryPolicy(RetryPolicy):
    """Retry policy for navigation operations.

    - 3 attempts
    - Exponential backoff (1s, 2s, 4s)
    - Retries: BrowserNavigationError, BrowserTimeoutError, BrowserNetworkError
    """

    def __init__(self, cleanup: Callable[[], Any] | None = None) -> None:
        """Initialize navigation retry policy.

        Args:
            cleanup: Optional cleanup function (e.g., page.goto("about:blank"))
        """
        super().__init__(
            max_attempts=3,
            base_delay_ms=1000,
            backoff_multiplier=2.0,
            should_retry=lambda exc: isinstance(
                exc, (BrowserNavigationError, BrowserTimeoutError, BrowserNetworkError)
            ),
            cleanup=cleanup,
        )


class LaunchRetryPolicy(RetryPolicy):
    """Retry policy for browser launch operations.

    - 2 attempts
    - Fixed delay (2s)
    - Retries: BrowserLaunchError
    """

    def __init__(self, cleanup: Callable[[], Any] | None = None) -> None:
        """Initialize launch retry policy.

        Args:
            cleanup: Optional cleanup function
        """
        super().__init__(
            max_attempts=2,
            base_delay_ms=2000,
            backoff_multiplier=1.0,  # Fixed delay
            should_retry=lambda exc: isinstance(exc, BrowserLaunchError),
            cleanup=cleanup,
        )


class NetworkRetryPolicy(RetryPolicy):
    """Retry policy for network operations.

    - 5 attempts
    - Exponential backoff (1s, 2s, 4s, 8s, 16s)
    - Retries: BrowserNetworkError, BrowserTimeoutError
    """

    def __init__(self, cleanup: Callable[[], Any] | None = None) -> None:
        """Initialize network retry policy.

        Args:
            cleanup: Optional cleanup function
        """
        super().__init__(
            max_attempts=5,
            base_delay_ms=1000,
            backoff_multiplier=2.0,
            should_retry=lambda exc: isinstance(exc, (BrowserNetworkError, BrowserTimeoutError)),
            cleanup=cleanup,
        )
