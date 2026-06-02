"""Page object pool with zero-copy reset strategy.


[INPUT]
- patchright.async_api::BrowserContext (POS: Patchright browser context)
- patchright.async_api::Page (POS: Patchright page instance)

[OUTPUT]
- PagePool: per-context page object pool with zero-copy reuse

[POS]
Page object pool. Implements zero-copy reset via CDP commands (clears cookies, storage, network state),
supports acquire/release lifecycle management with auto-scaling. Delegated by GlobalBrowserPool.
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
    """Page Object池 — 零拷贝复用，CDP fastReset.

     via  CDP 命令清EmptyPageState（清除 cookies、storage、网络State），
     avoid Trigger导航事件。SupportAuto扩缩容，Maximum池Size限制 prevent 内存泄漏。
    """

    def __init__(self, context: BrowserContext, max_size: int = 10) -> None:
        """InitializePage池.

        Args:
            context: 所属  BrowserContext
            max_size: Maximum池Size(超出后Close而非复用)

        """
        self._context = context
        self._idle: list[Page] = []
        self._busy: set[Page] = set()
        self._max_size = max_size
        self._lock = asyncio.Lock()
        self._total_acquires = 0
        self._total_resets = 0
        self._fast_reset_success = 0
        self._fast_reset_failures = 0

    async def acquire(self) -> Page:
        """Get一个可用  Page(复用 or Createnew ).

        Returns:
             already Reset  Page Instance

        """
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
        """Release一个 Page 回池( or Close).

        Args:
            page: 要Release  Page Instance

        """
        async with self._lock:
            self._busy.discard(page)

            if len(self._idle) < self._max_size:
                self._idle.append(page)
            else:
                with contextlib.suppress(Exception):
                    await page.close()

    async def _reset_page(self, page: Page) -> None:
        """零拷贝ResetPageState.

        优先 using  CDP 命令（fast），Failure时fallback to  goto('about:blank')
        """
        self._total_resets += 1
        success = await self._fast_reset(page)

        if not success:
            self._fast_reset_failures += 1
            logger.warning("Fast reset failed, falling back to goto('about:blank')")
            await self._fallback_reset(page)
        else:
            self._fast_reset_success += 1

    async def _fast_reset(self, page: Page) -> bool:
        """CDP 零拷贝Reset.

        Returns:
            True if success, False if CDP failed

        """
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
        """fallbackResetStrategy — goto('about:blank')."""
        try:
            await asyncio.wait_for(
                page.goto("about:blank", wait_until="domcontentloaded"),
                timeout=_FALLBACK_RESET_TIMEOUT_MS / 1000,
            )
        except Exception as exc:
            logger.warning(f"Fallback reset (goto) failed: {exc}")

    async def shutdown(self) -> None:
        """CloseAll Page 并清Empty池."""
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
        """GetStatisticsinformation( for 监控)."""
        return {
            "idle": len(self._idle),
            "busy": len(self._busy),
            "total_acquires": self._total_acquires,
            "total_resets": self._total_resets,
            "fast_reset_success": self._fast_reset_success,
            "fast_reset_failures": self._fast_reset_failures,
            "fast_reset_success_rate": (self._fast_reset_success / self._total_resets if self._total_resets > 0 else 0),
        }
