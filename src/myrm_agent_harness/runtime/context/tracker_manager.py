"""Generic singleton manager for tracker instances.

Provides thread-safe lazy initialization with async support for tracker objects.

[INPUT]
- (none)

[OUTPUT]
- TrackerManager: Generic singleton manager for tracker instances.

[POS]
Generic singleton manager for tracker instances.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class TrackerManager[T]:
    """Generic singleton manager for tracker instances.

    Provides thread-safe lazy initialization with async support.

    Args:
        factory: Async factory function to create tracker instance

    Example:
        >>> async def create_tracker():
        ...     return MyTracker(db_path="...")
        >>> manager = TrackerManager(create_tracker)
        >>> tracker = await manager.get_instance()

    """

    def __init__(self, factory: Callable[[], Awaitable[T]]) -> None:
        self._instance: T | None = None
        self._lock = asyncio.Lock()
        self._factory = factory

    async def get_instance(self) -> T:
        """Get or create tracker instance (thread-safe lazy initialization).

        Returns:
            Tracker instance
        """
        if self._instance is not None:
            return self._instance

        async with self._lock:
            if self._instance is None:
                self._instance = await self._factory()
            return self._instance

    async def reset(self) -> None:
        """Reset singleton instance (for testing)."""
        async with self._lock:
            self._instance = None
