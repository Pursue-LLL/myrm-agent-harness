"""Tool fallback registry for automatic tool switching on degradation.

[INPUT]
无直接依赖（独立模块）

[OUTPUT]
- FallbackChain: Fallback配置（primary + fallbacks + cache）
- ToolFallbackRegistry: Fallback注册中心，秒级自动切换工具

[POS]
Tool fallback mechanism. Sub-second automatic switching (<3s), smart execution order (last_success first), and cache fallback.

"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FallbackChain:
    """Fallback configuration for a tool."""

    primary_tool: str
    fallbacks: list[str]  # Ordered list of fallback tools
    cache_ttl: int = 3600  # Cache TTL in seconds (default 1 hour)
    _last_success: str | None = None  # Last successful tool in chain
    _cache: dict[str, tuple[Any, float]] = field(default_factory=dict)  # key → (value, timestamp)

    def get_execution_order(self) -> list[str]:
        """Get tool execution order (primary + fallbacks).

        Optimized order: last_success first if available.

        Returns:
            Ordered list of tool names to try
        """
        order = [self.primary_tool, *self.fallbacks]

        # Optimization: try last successful tool first
        if self._last_success and self._last_success in order:
            order.remove(self._last_success)
            order.insert(0, self._last_success)

        return order

    def mark_success(self, tool_name: str) -> None:
        """Mark tool as successful (for optimization)."""
        self._last_success = tool_name

    def get_cache(self, key: str) -> Any | None:
        """Get cached result if not expired.

        Args:
            key: Cache key

        Returns:
            Cached value or None if expired/missing
        """
        if key not in self._cache:
            return None

        value, timestamp = self._cache[key]
        if time.time() - timestamp > self.cache_ttl:
            del self._cache[key]
            return None

        return value

    def set_cache(self, key: str, value: Any) -> None:
        """Set cache value with current timestamp."""
        self._cache[key] = (value, time.time())


class ToolFallbackRegistry:
    """Registry for tool fallback configurations.

    Enables automatic tool switching on degradation without waiting for
    FIX evolution. Response time: seconds vs minutes.

    Features beyond OpenSpace:
    - Configurable fallback chains
    - Smart execution order (last_success optimization)
    - Optional cache fallback
    - Async non-blocking
    """

    def __init__(self):
        """Initialize fallback registry."""
        # tool_name → FallbackChain
        self._chains: dict[str, FallbackChain] = {}

        # Statistics
        self._total_fallbacks = 0
        self._fallback_success_count = 0

    def register_fallback(self, primary_tool: str, fallbacks: list[str], cache_ttl: int = 3600) -> None:
        """Register fallback chain for a tool.

        Args:
            primary_tool: Primary tool name
            fallbacks: Ordered list of fallback tools
            cache_ttl: Cache TTL in seconds (default 3600)
        """
        self._chains[primary_tool] = FallbackChain(primary_tool=primary_tool, fallbacks=fallbacks, cache_ttl=cache_ttl)
        logger.info(f"[ToolFallback] Registered {primary_tool} → {fallbacks} (cache_ttl={cache_ttl}s)")

    async def execute_with_fallback(
        self, primary_tool: str, executor: Callable[[str], Any], cache_key: str | None = None, use_cache: bool = True
    ) -> tuple[Any, str]:
        """Execute tool with automatic fallback on failure.

        Args:
            primary_tool: Primary tool name
            executor: Async function (tool_name) → result
            cache_key: Optional cache key for result caching
            use_cache: Whether to use cache fallback (default True)

        Returns:
            Tuple of (result, tool_name_used)

        Raises:
            Exception: If all tools in chain failed
        """
        chain = self._chains.get(primary_tool)
        if not chain:
            # No fallback configured, execute primary directly
            result = await executor(primary_tool)
            return result, primary_tool

        # Try cache first if enabled and available
        if use_cache and cache_key:
            cached = chain.get_cache(cache_key)
            if cached is not None:
                logger.info(f"[ToolFallback] Cache hit for {primary_tool}")
                return cached, f"{primary_tool}:cache"

        # Try tools in execution order
        execution_order = chain.get_execution_order()
        last_error: Exception | None = None

        for tool_name in execution_order:
            try:
                logger.debug(f"[ToolFallback] Trying {tool_name}")
                result = await executor(tool_name)

                # Success
                chain.mark_success(tool_name)
                if use_cache and cache_key:
                    chain.set_cache(cache_key, result)

                if tool_name != primary_tool:
                    self._total_fallbacks += 1
                    self._fallback_success_count += 1
                    logger.info(f"[ToolFallback] Fallback success: {primary_tool} → {tool_name}")

                return result, tool_name

            except Exception as e:
                last_error = e
                logger.warning(f"[ToolFallback] {tool_name} failed: {e}")
                continue

        # All tools failed
        self._total_fallbacks += 1
        logger.error(f"[ToolFallback] All tools failed for {primary_tool}: {last_error}")
        raise last_error or Exception(f"All fallbacks failed for {primary_tool}")

    def get_stats(self) -> dict:
        """Get fallback statistics.

        Returns:
            Dict with:
            - total_fallbacks: Total fallback attempts
            - fallback_success_count: Successful fallbacks
            - fallback_success_rate: Success rate (0.0-1.0)
            - registered_chains: Number of registered fallback chains
        """
        return {
            "total_fallbacks": self._total_fallbacks,
            "fallback_success_count": self._fallback_success_count,
            "fallback_success_rate": (
                self._fallback_success_count / self._total_fallbacks if self._total_fallbacks > 0 else 0.0
            ),
            "registered_chains": len(self._chains),
        }
