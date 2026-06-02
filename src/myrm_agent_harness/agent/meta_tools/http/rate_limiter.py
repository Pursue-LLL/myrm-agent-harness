"""Rate Limiter - Concurrency Control for HTTP Requests

[INPUT]

[OUTPUT]
- Rate limiting protocol

[POS]
Rate limiter interface (framework layer). Defines the rate limiting protocol with a default token-bucket implementation.

"""

from __future__ import annotations

from typing import Protocol


class RateLimiterProtocol(Protocol):
    """Rate limiter protocol (Framework layer interface)

    Business layer should implement this protocol to provide rate limiting.
    Framework layer only defines the interface, does not couple with specific algorithm implementation.

    Example implementations:
    - TokenBucketRateLimiter: Token bucket algorithm (for smooth rate limiting)
    - LeakyBucketRateLimiter: Leaky bucket algorithm (for burst protection)
    - SlidingWindowRateLimiter: Sliding window algorithm (for precise rate limiting)

    Use cases:
    - Client-side rate limiting: Prevent client from exceeding API rate limits (e.g., GitHub API: 5000 req/h)
    - Server-side rate limiting: Prevent server from being overwhelmed by requests
    - Multi-tenant SaaS: Different rate limits for different tenants (implemented in control plane)
    """

    async def acquire(self, tokens: int = 1) -> None:
        """Acquire tokens (blocks if not enough tokens available)

        Args:
            tokens: Number of tokens to acquire (default: 1)

        Raises:
            asyncio.TimeoutError: If tokens cannot be acquired within timeout

        Example:
            rate_limiter = TokenBucketRateLimiter(rate=10, capacity=100)  # 10 req/s, burst 100
            await rate_limiter.acquire(tokens=1)  # Acquire 1 token
            # Make HTTP request...
        """
        ...


class TokenBucketRateLimiter:
    """Token bucket rate limiter (business layer example implementation)

    This is a simple example implementation using token bucket algorithm.
    For production use, consider:
    - LeakyBucketRateLimiter: For burst protection
    - SlidingWindowRateLimiter: For precise rate limiting
    - DistributedRateLimiter: For multi-tenant SaaS scenarios (using Redis/Memcached)
    """

    def __init__(self, rate: float, capacity: int):
        """Initialize token bucket rate limiter

        Args:
            rate: Token refill rate (tokens per second)
            capacity: Token bucket capacity (max burst)

        Example:
            rate_limiter = TokenBucketRateLimiter(rate=10, capacity=100)  # 10 req/s, burst 100
        """
        self._rate = rate
        self._capacity = capacity
        self._tokens = capacity
        self._last_refill_time = 0.0

    async def acquire(self, tokens: int = 1) -> None:
        """Acquire tokens (blocks if not enough tokens available)"""
        import asyncio
        import time

        while True:
            # Refill tokens
            now = time.time()
            elapsed = now - self._last_refill_time
            refilled_tokens = elapsed * self._rate
            self._tokens = min(self._capacity, self._tokens + refilled_tokens)
            self._last_refill_time = now

            # Check if enough tokens
            if self._tokens >= tokens:
                self._tokens -= tokens
                return

            # Wait for tokens to refill
            wait_time = (tokens - self._tokens) / self._rate
            await asyncio.sleep(wait_time)
