"""Concurrency limiter for parallel execution.

[INPUT]
- asyncio::Semaphore (POS: async concurrency primitive)
- types::TracebackType (POS: exception traceback type)
- typing::Self (POS: current class type marker)

[OUTPUT]
- ConcurrencyLimiter: Async semaphore wrapper for limiting concurrent LLM calls.

[POS]
Concurrency limiter for parallel execution. Provides an async context manager around a semaphore.
"""

import asyncio
from types import TracebackType
from typing import Self


class ConcurrencyLimiter:
    """Async semaphore wrapper for limiting concurrent LLM calls."""

    def __init__(self, max_concurrent: int = 3) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be at least 1")
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def __aenter__(self) -> Self:
        await self._semaphore.acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self._semaphore.release()
