"""Cancel-safe claim on one page slot of the global browser pool.

[INPUT]
- patchright.async_api::Page (POS: Patchright page instance)
- .page_pool::PagePool (POS: per-context page pool a claimed page is taken from)

[OUTPUT]
- PageAcquisition: async context manager that holds one concurrency permit, plus the page taken from a PagePool, until the caller has counted the page as in use

[POS]
Acquiring a page crosses several suspension points (memory check, browser launch, context
creation, page reset, pool lock). A caller cancelled at any of them would otherwise keep the
permit forever (the pool is a process-wide singleton and the permit count is never reconciled)
and leave a taken page parked as busy but uncounted, which also blocks destroying its context.
`PageAcquisition` hands back whatever is still held when the block fails or is cancelled and
steps aside once `commit()` marks the page as counted, after which `release_page` owns it.
A page whose creation call itself is cancelled has no handle to hand back; it stays in its
context and is closed when that context is destroyed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from types import TracebackType

    from patchright.async_api import Page

    from .page_pool import PagePool

logger = logging.getLogger(__name__)


class PageAcquisition:
    """Holds a permit (and the page taken from a pool) until the page is counted as in use."""

    __slots__ = ("_committed", "_crash_handled_pages", "_page", "_pool", "_semaphore")

    def __init__(self, semaphore: asyncio.Semaphore, crash_handled_pages: set[int]) -> None:
        """Bind the permit source.

        Args:
            semaphore: Global concurrency semaphore of the pool.
            crash_handled_pages: ids of pages whose permit a crash handler already returned.
        """
        self._semaphore = semaphore
        self._crash_handled_pages = crash_handled_pages
        self._pool: PagePool | None = None
        self._page: Page | None = None
        self._committed = False

    async def __aenter__(self) -> Self:
        await self._semaphore.acquire()
        return self

    def hold(self, pool: PagePool, page: Page) -> None:
        """Record a page taken from `pool` that is not yet counted as in use."""
        self._pool = pool
        self._page = page

    def commit(self) -> None:
        """The page is counted as in use; `release_page` now owns the page and its permit."""
        self._committed = True

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is None or self._committed:
            return
        try:
            if self._pool is not None and self._page is not None:
                await self._pool.release(self._page)
        except Exception:
            logger.warning("PageAcquisition: could not hand back the unclaimed page", exc_info=True)
        finally:
            self._return_permit()

    def _return_permit(self) -> None:
        """Give the permit back unless a crash handler already did for the held page."""
        if self._page is not None and id(self._page) in self._crash_handled_pages:
            self._crash_handled_pages.discard(id(self._page))
            return
        self._semaphore.release()
