"""Three-layer crash detection and semaphore safety net for browser pool.

[INPUT]
- patchright.async_api::Page (POS: Patchright page instance)
- .browser_launcher::BrowserInstance (POS: browser instance metadata)
- .circuit_breaker::CircuitBreaker (POS: circuit breaker)

[OUTPUT]
- CrashWatchdogMixin: three-layer crash detection + semaphore safety net mixin

[POS]
Provides automatic crash recovery for GlobalBrowserPool:
- L1: browser.on('disconnected') real-time browser process crash detection
- L2: page.on('crash') real-time page renderer crash detection
- L3: _lifecycle_tick periodic fallback (30s interval)
- Semaphore safety net: prevents semaphore leaks or double releases on crash
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from patchright.async_api import Page

    from .browser_launcher import BrowserInstance
    from .circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


class CrashWatchdogMixin:
    """Three-layer crash detection mixin for GlobalBrowserPool.

    Provides browser disconnect (L1), page crash (L2) event handlers,
    lifecycle tick health checks (L3), and semaphore safety net logic.

    Requires host class to have:
    - _browsers: list[BrowserInstance]
    - _lock: asyncio.Lock
    - _global_semaphore: asyncio.Semaphore
    - _current_pages_in_use: int
    - _circuit_breaker: CircuitBreaker | None
    - _config: BrowserPoolConfig (with idle_timeout_seconds)
    """

    _browsers: list[BrowserInstance]
    _lock: asyncio.Lock
    _global_semaphore: asyncio.Semaphore
    _current_pages_in_use: int
    _circuit_breaker: CircuitBreaker | None
    _crash_handled_pages: set[int]
    _crash_count_browser: int
    _crash_count_page: int
    _crash_tasks: set[asyncio.Task[None]]

    def _register_disconnect_handler(self, inst: BrowserInstance) -> None:
        """Register browser.on('disconnected') for real-time crash detection (L1)."""

        def _on_disconnected() -> None:
            crash_task = asyncio.create_task(self._handle_browser_disconnected(inst))
            self._crash_tasks.add(crash_task)
            crash_task.add_done_callback(self._crash_tasks.discard)

        inst.browser.on("disconnected", _on_disconnected)

    async def _handle_browser_disconnected(self, inst: BrowserInstance) -> None:
        """Handle browser disconnect event — release semaphore slots and cleanup.

        For external (CDP-connected) browsers, disconnect is normal (user closed Chrome),
        not a crash — do not increment crash_count or trigger circuit breaker.
        """
        is_external = not inst.is_managed

        async with self._lock:
            if inst._disconnected:
                return
            inst._disconnected = True

            if not is_external:
                self._crash_count_browser += 1

            slots_to_release = inst.load
            self._current_pages_in_use = max(0, self._current_pages_in_use - slots_to_release)

            if inst in self._browsers:
                self._browsers.remove(inst)

            if self._circuit_breaker and not is_external:
                self._circuit_breaker.record_failure()

        for _ in range(slots_to_release):
            self._global_semaphore.release()

        if is_external:
            logger.info(f"External browser disconnected — released {slots_to_release} semaphore slots")
        else:
            logger.warning(
                f"Browser crashed — released {slots_to_release} semaphore slots, "
                f"crash_count_browser={self._crash_count_browser}",
            )

        await self._close_browser_instance(inst)

    def _register_page_crash_handler(self, page: Page, inst: BrowserInstance) -> None:
        """Register page.on('crash') for real-time page crash detection (L2)."""

        def _on_page_crash() -> None:
            crash_task = asyncio.create_task(self._handle_page_crashed(page, inst))
            self._crash_tasks.add(crash_task)
            crash_task.add_done_callback(self._crash_tasks.discard)

        page.on("crash", _on_page_crash)

    async def _handle_page_crashed(self, page: Page, inst: BrowserInstance) -> None:
        """Handle page crash event — release one semaphore slot and track for safety net."""
        page_id = id(page)

        async with self._lock:
            if inst._disconnected or page_id in self._crash_handled_pages:
                return

            self._crash_handled_pages.add(page_id)
            self._crash_count_page += 1
            inst.load = max(0, inst.load - 1)
            self._current_pages_in_use = max(0, self._current_pages_in_use - 1)

            for pool in inst.page_pools.values():
                pool._busy.discard(page)

        self._global_semaphore.release()

        logger.warning(
            f"Page crashed — released 1 semaphore slot, crash_count_page={self._crash_count_page}",
        )

    async def _lifecycle_tick(self) -> None:
        """Single lifecycle iteration: health-check all browsers + idle eviction (L3).

        Checks ALL browsers (not just idle ones) to catch crashed browsers with active load.
        For crashed browsers with load > 0, releases their semaphore slots.
        """
        # Phase 1 (lock): snapshot ALL browsers
        async with self._lock:
            all_browsers = list(self._browsers)

        if not all_browsers:
            return

        # Phase 2 (no lock): parallel health check on ALL browsers
        check_results = await asyncio.gather(
            *[self._check_browser_alive(inst) for inst in all_browsers],
        )

        # Phase 3 (lock): handle crashed + idle eviction
        evicted: list[tuple[BrowserInstance, int]] = []
        now = time.monotonic()
        idle_timeout = self._config.idle_timeout_seconds  # type: ignore[attr-defined]

        async with self._lock:
            for inst, alive in zip(all_browsers, check_results, strict=False):
                if inst not in self._browsers or inst._disconnected:
                    continue

                if not alive:
                    slots_to_release = inst.load
                    inst._disconnected = True
                    is_external = not inst.is_managed
                    if not is_external:
                        self._crash_count_browser += 1
                    self._current_pages_in_use = max(0, self._current_pages_in_use - slots_to_release)
                    if is_external:
                        logger.info(
                            f"Lifecycle: external browser disconnected (load={slots_to_release}), removing from pool"
                        )
                    else:
                        logger.warning(f"Lifecycle: browser crashed (load={slots_to_release}), removing from pool")
                    self._browsers.remove(inst)
                    evicted.append((inst, slots_to_release))
                    if self._circuit_breaker and not is_external:
                        self._circuit_breaker.record_failure()
                    continue

                if inst.load == 0 and idle_timeout > 0 and (now - inst.last_active_at) > idle_timeout:
                    logger.info(
                        f"Lifecycle: evicting idle browser (idle {now - inst.last_active_at:.0f}s > {idle_timeout}s)"
                    )
                    self._browsers.remove(inst)
                    evicted.append((inst, 0))

        # Phase 4 (no lock): release semaphore slots + close evicted instances
        for inst, slots in evicted:
            for _ in range(slots):
                self._global_semaphore.release()
            await self._close_browser_instance(inst)

    @staticmethod
    async def _check_browser_alive(inst: BrowserInstance) -> bool:
        try:
            if callable(getattr(inst.browser, "version", None)):
                await asyncio.wait_for(inst.browser.version(), timeout=2.0)
            else:
                await asyncio.wait_for(inst.browser.contexts(), timeout=2.0)
            return True
        except (TimeoutError, RuntimeError, OSError, asyncio.CancelledError, TypeError):
            return False

    @staticmethod
    async def _close_browser_instance(inst: BrowserInstance) -> None:
        """Gracefully close all resources owned by a BrowserInstance."""
        for pool in inst.page_pools.values():
            with contextlib.suppress(Exception):
                await pool.shutdown()
        for ctx in inst.contexts.values():
            with contextlib.suppress(Exception):
                await ctx.close()
        with contextlib.suppress(Exception):
            await inst.browser.close()
