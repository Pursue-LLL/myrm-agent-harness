"""Page object pool with zero-copy reset strategy.


[INPUT]
- patchright.async_api::BrowserContext (POS: Patchright browser context)
- patchright.async_api::Page (POS: Patchright page instance)

[OUTPUT]
- PagePool: per-context page pool with managed full-reset or external session-preserving reset

[POS]
Page object pool. Implements zero-copy reset via CDP commands for managed browsers, and
session-preserving reset for CDP-attached external Chrome (no global cookie wipe).
Supports acquire/release lifecycle management with auto-scaling. Delegated by GlobalBrowserPool.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from patchright.async_api import BrowserContext, CDPSession, Page

logger = logging.getLogger(__name__)

_RESET_TIMEOUT_MS = 3000
_FALLBACK_RESET_TIMEOUT_MS = 5000


class PagePool:
    """Per-context page pool with CDP fast reset and optional session preservation."""

    def __init__(
        self,
        context: BrowserContext,
        max_size: int = 10,
        *,
        preserve_session: bool = False,
    ) -> None:
        """Initialize the page pool.

        Args:
            context: Owning browser context.
            max_size: Max idle pages kept for reuse (overflow pages are closed).
            preserve_session: When True, skip global cookie/storage wipe on reuse
                (for CDP-attached user Chrome where login state must persist).
        """
        self._context = context
        self._preserve_session = preserve_session
        self._idle: list[Page] = []
        self._busy: set[Page] = set()
        self._max_size = max_size
        self._lock = asyncio.Lock()
        self._total_acquires = 0
        self._total_resets = 0
        self._fast_reset_success = 0
        self._fast_reset_failures = 0

    async def acquire(self) -> Page:
        """Return a ready page, reusing and resetting an idle page when possible."""
        async with self._lock:
            self._total_acquires += 1

            if self._idle:
                page = self._idle.pop()
                await self._reset_page(page)
                self._busy.add(page)
                return page

            page = await self._context.new_page()
            self._busy.add(page)
            return page

    async def release(self, page: Page) -> None:
        """Return a page to the idle pool or close it when the pool is full."""
        async with self._lock:
            self._busy.discard(page)

            if len(self._idle) < self._max_size:
                self._idle.append(page)
            else:
                with contextlib.suppress(Exception):
                    await page.close()

    async def _reset_page(self, page: Page) -> None:
        """Reset page state before reuse (full wipe or session-preserving)."""
        self._total_resets += 1
        success = await self._fast_reset(page)

        if not success:
            self._fast_reset_failures += 1
            logger.warning("Fast reset failed, falling back to goto('about:blank')")
            await self._fallback_reset(page)
        else:
            self._fast_reset_success += 1

    async def _fast_reset(self, page: Page) -> bool:
        """CDP fast reset. Skips global cookie wipe when preserve_session is enabled."""
        if self._preserve_session:
            return await self._fast_reset_preserve_session(page)
        return await self._fast_reset_managed(page)

    async def _fast_reset_preserve_session(self, page: Page) -> bool:
        """Reset navigation state only — keep browser profile cookies intact."""
        try:
            cdp: CDPSession = await page.context.new_cdp_session(page)
            await asyncio.wait_for(
                cdp.send("Page.resetNavigationHistory"),
                timeout=_RESET_TIMEOUT_MS / 1000,
            )
            await cdp.detach()
            await self._fallback_reset(page)
            return True
        except Exception as exc:
            logger.warning(f"Session-preserving CDP reset failed: {exc}")
            return False

    async def _fast_reset_managed(self, page: Page) -> bool:
        """Full CDP reset for managed (launched) browser instances."""
        try:
            cdp: CDPSession = await page.context.new_cdp_session(page)

            await asyncio.wait_for(
                asyncio.gather(
                    cdp.send("Page.resetNavigationHistory"),
                    cdp.send(
                        "Storage.clearDataForOrigin",
                        {
                            "origin": "*",
                            "storageTypes": "cookies,local_storage,session_storage,cache_storage,indexeddb",
                        },
                    ),
                    cdp.send("Network.clearBrowserCookies"),
                    cdp.send("Network.clearBrowserCache"),
                    return_exceptions=True,
                ),
                timeout=_RESET_TIMEOUT_MS / 1000,
            )

            await cdp.detach()
            return True

        except Exception as exc:
            logger.warning(f"CDP fast reset failed: {exc}")
            return False

    async def _fallback_reset(self, page: Page) -> None:
        """Fallback reset — navigate to about:blank."""
        try:
            await asyncio.wait_for(
                page.goto("about:blank", wait_until="domcontentloaded"),
                timeout=_FALLBACK_RESET_TIMEOUT_MS / 1000,
            )
        except Exception as exc:
            logger.warning(f"Fallback reset (goto) failed: {exc}")

    async def shutdown(self) -> None:
        """Close all pages and clear the pool."""
        async with self._lock:
            all_pages = list(self._idle) + list(self._busy)

            for page in all_pages:
                with contextlib.suppress(Exception):
                    await page.close()

            self._idle.clear()
            self._busy.clear()

            logger.warning(
                f"PagePool shutdown — stats: acquires={self._total_acquires}, "
                f"resets={self._total_resets}, fast_success={self._fast_reset_success}, "
                f"fast_failures={self._fast_reset_failures}",
            )

    @property
    def active_pages_count(self) -> int:
        """Get the number of currently busy/active pages."""
        return len(self._busy)

    @property
    def stats(self) -> dict[str, int | float]:
        """Return pool statistics for monitoring."""
        return {
            "idle": len(self._idle),
            "busy": len(self._busy),
            "total_acquires": self._total_acquires,
            "total_resets": self._total_resets,
            "fast_reset_success": self._fast_reset_success,
            "fast_reset_failures": self._fast_reset_failures,
            "fast_reset_success_rate": (self._fast_reset_success / self._total_resets if self._total_resets > 0 else 0),
        }
