"""Global browser pool with intelligent scheduling and multi-tenant isolation.


[INPUT]
- patchright.async_api::Page (POS: Patchright page instance)
- .browser_launcher::BrowserLauncher, BrowserInstance (POS: browser launcher and instance metadata)
- .context_factory::ContextFactory (POS: context creation factory)
- .page_pool::PagePool (POS: page object pool)
- .config::BrowserPoolConfig (POS: browser pool config)
- .throttle::ThrottleStrategy, create_throttle_strategy (POS: throttle strategy)
- .circuit_breaker::CircuitBreaker (POS: circuit breaker)

[OUTPUT]
- ContextType: context purpose classification enum (CRAWL/AGENT/STEALTH)
- GlobalBrowserPool: global browser pool (smart scheduling, resource management, automatic crash recovery)

[POS]
Global browser resource pool. Manages Browser/Context/Page three-layer resources, implementing:
1. Zero-copy page reuse (delegates to PagePool)
2. Smart load scheduling (least-loaded first)
3. Type-based isolation (CRAWL/AGENT/STEALTH each with independent resource pools)
4. Elastic scaling (dynamically creates/destroys Browser instances)
5. Global concurrency limit (Semaphore controls total concurrency)
6. Lifecycle management (background loop: idle reclamation + crash detection)
7. Three-layer automatic crash recovery (L1: browser disconnect event, L2: page crash event, L3: lifecycle fallback)
8. Semaphore safety net (prevents semaphore leaks or double releases on crash)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
import time
from enum import Enum
from typing import TYPE_CHECKING

from .browser_launcher import BrowserInstance, BrowserLauncher
from .circuit_breaker import CircuitBreaker
from .config import (
    MAX_CONTEXTS_PER_BROWSER,
    SCALE_OUT_LOAD_THRESHOLD,
    BrowserEngine,
    BrowserPoolConfig,
)
from .context_factory import ContextFactory
from .crash_watchdog import CrashWatchdogMixin
from .memory_guard import MemoryGuard
from .page_pool import PagePool
from .proxy import ProxyPool
from .throttle import ThrottleStrategy, create_throttle_strategy

if TYPE_CHECKING:
    from patchright.async_api import Page

logger = logging.getLogger(__name__)

_DEFAULT_LAUNCH_OPTIONS: dict[str, object] = {
    "headless": os.getenv("VISUAL_DESKTOP") != "1",
    "args": [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--no-sandbox",
        "--disable-background-networking",
        "--disable-extensions",
        "--disable-gpu",
        "--disable-plugins",
    ],
}

if os.getenv("VISUAL_DESKTOP") == "1" and sys.platform != "darwin":
    _DEFAULT_LAUNCH_OPTIONS["env"] = {**os.environ, "DISPLAY": ":99"}


class ContextType(Enum):
    """Context purpose classification.

    Different purposes use different launch parameters and resource isolation strategies.
    """

    CRAWL = "crawl"
    AGENT = "agent"
    STEALTH = "stealth"


class GlobalBrowserPool(CrashWatchdogMixin):
    """Global browser pool — zero-copy, smart scheduling, type isolation, concurrency limits, lifecycle management.

    Singleton architecture, initialized at app startup, warmup and shutdown during FastAPI lifespan.

    Core features:
    1. Zero-copy reuse: PagePool rapidly resets pages via CDP commands
    2. Smart scheduling: least-load-first, dynamic scaling
    3. Type isolation: CRAWL/AGENT/STEALTH contexts with independent resource pools
    4. Elastic scaling: auto-creates new Browsers under high load, up to max_browsers
    5. Global concurrency limit: Semaphore controls total concurrent page count
    6. Lifecycle management: background loop auto-reclaims idle Browsers + detects and removes crashed instances
    """

    def __init__(
        self,
        max_browsers: int = 5,
        launch_options: dict[str, object] | None = None,
        proxy_pool: ProxyPool | None = None,
        config: BrowserPoolConfig | None = None,
    ) -> None:
        """Initialize global browser pool.

        Args:
            max_browsers: Maximum Browser instance count
            launch_options: Patchright launch options (optional)
            proxy_pool: Proxy pool (supports rotation and sticky sessions)
            config: Browser pool configuration (concurrency/rate-limiting/circuit-breaker/resource interception)

        """
        self._browsers: list[BrowserInstance] = []
        self._max_browsers = max_browsers
        self._proxy_pool = proxy_pool
        self._lock = asyncio.Lock()
        self._total_acquires = 0
        self._total_releases = 0
        self._current_pages_in_use = 0

        self._crash_handled_pages: set[int] = set()
        self._crash_count_browser = 0
        self._crash_count_page = 0
        self._crash_tasks: set[asyncio.Task[None]] = set()

        self._config = config or BrowserPoolConfig()
        self._global_semaphore = asyncio.Semaphore(self._config.max_concurrent_pages)
        self._throttle_strategy = create_throttle_strategy(self._config.rate_limiter)
        self._memory_guard = MemoryGuard(self._config.memory_guard)

        cb_config = self._config.circuit_breaker
        self._circuit_breaker = (
            CircuitBreaker(
                failure_threshold=cb_config.failure_threshold,
                timeout=cb_config.timeout,
                callback=None,
            )
            if cb_config.enabled
            else None
        )

        # Dictionary of launchers keyed by BrowserEngine
        self._launchers: dict[BrowserEngine, BrowserLauncher] = {}
        self._launch_options = launch_options or dict(_DEFAULT_LAUNCH_OPTIONS)

        self._context_factory = ContextFactory(
            proxy_pool=self._proxy_pool,
            default_emulation=self._config.default_emulation,
        )
        self._lifecycle_task: asyncio.Task[None] | None = None

        logger.info(
            f"GlobalBrowserPool initialized — max_concurrent_pages={self._config.max_concurrent_pages}, "
            f"mode={self._config.mode}, "
            f"launch_mode={self._config.launch_mode}, "
            f"throttle_mode={self._config.rate_limiter.mode}, "
            f"memory_guard={self._config.memory_guard.enabled}, "
            f"circuit_breaker={cb_config.enabled}, "
            f"idle_timeout={self._config.idle_timeout_seconds}s, "
            f"proxy_pool={'enabled' if self._proxy_pool else 'disabled'}",
        )

    def _get_launcher(self, engine: BrowserEngine) -> BrowserLauncher:
        """Get or create a BrowserLauncher for the specified engine."""
        if engine not in self._launchers:
            self._launchers[engine] = BrowserLauncher(
                launch_options=self._launch_options,
                launch_mode=self._config.launch_mode,
                engine=engine,
                cdp_endpoint=self._config.cdp_endpoint,
                remote_ws_endpoint=self._config.remote_ws_endpoint,
                remote_ws_headers=self._config.remote_ws_headers,
            )
        return self._launchers[engine]

    async def warmup(self, browsers: int = 2, pages_per_context: int = 5) -> None:
        """Warm up pool (called at app startup).

        Creates the specified number of Browser instances and pre-creates Contexts and Pages for each ContextType.
        Warms up the default engine.

        Args:
            browsers: Number of Browsers to pre-create
            pages_per_context: Number of Pages to pre-create per Context

        """
        logger.info(f"GlobalBrowserPool warmup: browsers={browsers}, pages={pages_per_context}")

        launcher = self._get_launcher(self._config.engine)
        for _ in range(browsers):
            inst = await launcher.create_browser()
            self._register_disconnect_handler(inst)
            self._browsers.append(inst)

            for ctx_type in [ContextType.CRAWL, ContextType.AGENT]:
                ctx_key = f"{ctx_type.value}_warmup"
                inst.contexts[ctx_key] = await self._context_factory.create_context(inst.browser, ctx_type.value)
                pool = PagePool(inst.contexts[ctx_key], max_size=pages_per_context * 2)
                inst.page_pools[ctx_key] = pool

                for _ in range(pages_per_context):
                    page = await pool.acquire()
                    await pool.release(page)

        logger.info("GlobalBrowserPool warmup completed")

    async def acquire_page(
        self,
        context_type: ContextType,
        context_key: str | None = None,
        context_kwargs: dict[str, object] | None = None,
        engine_preference: BrowserEngine | None = None,
    ) -> tuple[Page, str]:
        """Smart page allocation (with global concurrency limit).

        Load-based smart scheduling, auto-creates or reuses Context/Page.
        Uses double-checked locking (DCL), holding lock only when modifying shared state.

        Args:
            context_type: Context type (CRAWL/AGENT/STEALTH)
            context_key: Context identifier (same key reuses Context, for session isolation)
            context_kwargs: Additional BrowserContext params (e.g. record_video_dir)
            engine_preference: Preferred browser engine. Falls back to config default if None.

        Returns:
            (page, context_key) — Page instance and actual context_key used

        """
        engine = engine_preference or self._config.engine
        await self._global_semaphore.acquire()

        try:
            await self._memory_guard.check_memory()

            # 1. Under lock: read state, update counters
            async with self._lock:
                self._total_acquires += 1
                browser_inst = await self._get_least_loaded_browser(engine)
                ctx_key = context_key or f"{context_type.value}_{id(self)}"
                needs_creation = ctx_key not in browser_inst.contexts

            # 2. Outside lock: create resources (DCL)
            if needs_creation:
                # Create Context (async I/O, no lock held)
                merged_kwargs = dict(context_kwargs) if context_kwargs else {}
                if "resource_block" not in merged_kwargs:
                    merged_kwargs["resource_block"] = self._config.resource_block

                new_context = await self._context_factory.create_context(
                    browser_inst.browser,
                    context_type.value,
                    extra_kwargs=merged_kwargs,
                    context_key=ctx_key,
                )
                new_pool = PagePool(new_context)

                # Under lock: check and insert (prevent duplicate creation)
                async with self._lock:
                    if ctx_key not in browser_inst.contexts:
                        browser_inst.contexts[ctx_key] = new_context
                        browser_inst.page_pools[ctx_key] = new_pool
                    else:
                        # Clean up unused resources (prevent leaks)
                        needs_creation = False
                        try:
                            await new_context.close()
                            await new_pool.shutdown()
                        except Exception as e:
                            logger.warning(f"Failed to cleanup unused context: {e}")

            # 3. Outside lock: acquire Page (async I/O) + register crash handler (L2)
            pool = browser_inst.page_pools[ctx_key]
            page = await pool.acquire()
            self._register_page_crash_handler(page, browser_inst)

            # 4. Under lock: update load count, concurrency count, active time
            async with self._lock:
                browser_inst.load += 1
                browser_inst.last_active_at = time.monotonic()
                self._current_pages_in_use += 1

            self._ensure_lifecycle_loop()
            return page, ctx_key

        except Exception:
            self._global_semaphore.release()
            raise

    async def destroy_context(self, context_key: str) -> None:
        """Explicitly destroy a context and its associated page pool.

        Args:
            context_key: The identifier of the context to destroy

        Raises:
            RuntimeError: If there are still active pages in the context's page pool.
        """
        logger.info(f"Attempting to destroy context: {context_key}")
        async with self._lock:
            for browser_inst in self._browsers:
                if context_key in browser_inst.contexts:
                    pool = browser_inst.page_pools.get(context_key)

                    # Safety Guard: Ensure no pages are currently in use
                    if pool and pool.active_pages_count > 0:
                        logger.error(
                            f"Concurrency Guard Triggered: {pool.active_pages_count} pages still active in {context_key}"
                        )
                        raise RuntimeError(
                            f"Cannot destroy context {context_key}: "
                            f"{pool.active_pages_count} pages are still in use. "
                            f"Ensure all pages are released before destroying."
                        )

                    context = browser_inst.contexts.pop(context_key)
                    if pool:
                        browser_inst.page_pools.pop(context_key)

                    try:
                        if pool:
                            await pool.shutdown()
                        await context.close()
                        logger.info(f"Successfully destroyed context: {context_key}")
                    except Exception as e:
                        logger.warning(f"Error while destroying context {context_key}: {e}")

                    # Also check if this browser instance has no more contexts, if so we could close it
                    if not browser_inst.contexts:
                        logger.info(
                            f"Browser instance {browser_inst.engine} has no more contexts, but keeping it alive for future use."
                        )
                    return

            logger.warning(f"Context {context_key} not found for destruction")

    async def release_page(self, page: Page, context_key: str) -> None:
        """Release Page back to pool (free global concurrency slot).

        Semaphore safety net: if the page/browser was already handled by a crash callback,
        skip semaphore release to prevent over-release.

        Args:
            page: Page instance to release
            context_key: context_key returned by acquire

        """
        page_id = id(page)
        skip_semaphore = False

        try:
            async with self._lock:
                self._total_releases += 1

                if page_id in self._crash_handled_pages:
                    self._crash_handled_pages.discard(page_id)
                    skip_semaphore = True
                    return

                self._current_pages_in_use = max(0, self._current_pages_in_use - 1)

                found = False
                for browser_inst in self._browsers:
                    if context_key in browser_inst.page_pools:
                        if browser_inst._disconnected:
                            skip_semaphore = True
                        else:
                            await browser_inst.page_pools[context_key].release(page)
                            browser_inst.load = max(0, browser_inst.load - 1)
                            browser_inst.last_active_at = time.monotonic()
                        found = True
                        break

                if not found:
                    skip_semaphore = True

        finally:
            if not skip_semaphore:
                self._global_semaphore.release()

    async def _get_least_loaded_browser(self, engine: BrowserEngine) -> BrowserInstance:
        """Load-aware scheduling — select the least-loaded Browser for the given engine.

        Prefers Browsers that have not reached max_contexts_per_browser.
        When all Browsers are heavily loaded, auto-scales by creating new Browsers (up to max_browsers).
        When max_browsers is reached, logs a warning and force-assigns to the least-loaded Browser.
        """
        launcher = self._get_launcher(engine)

        if not self._browsers:
            inst = await launcher.create_browser()
            self._register_disconnect_handler(inst)
            self._browsers.append(inst)
            return inst

        engine_browsers = [b for b in self._browsers if b.engine == engine.value]

        if not engine_browsers:
            inst = await launcher.create_browser()
            self._register_disconnect_handler(inst)
            self._browsers.append(inst)
            return inst

        # Prefer Browsers that have not reached contexts limit
        available_browsers = [b for b in engine_browsers if len(b.contexts) < MAX_CONTEXTS_PER_BROWSER]

        if available_browsers:
            least = min(available_browsers, key=lambda b: b.load)

            # If least-loaded Browser is still busy and max_browsers not reached, create new one
            if least.load > SCALE_OUT_LOAD_THRESHOLD and len(self._browsers) < self._max_browsers:
                inst = await launcher.create_browser()
                inst._engine = engine  # type: ignore
                self._register_disconnect_handler(inst)
                self._browsers.append(inst)
                return inst

            return least

        # All Browsers reached contexts limit
        if len(self._browsers) < self._max_browsers:
            inst = await launcher.create_browser()
            inst._engine = engine  # type: ignore
            self._register_disconnect_handler(inst)
            self._browsers.append(inst)
            return inst

        # max_browsers reached, log warning and force-assign
        logger.warning(
            f"All browsers at max_contexts_per_browser limit ({MAX_CONTEXTS_PER_BROWSER}), "
            f"forcing context creation on least loaded browser",
        )
        return min(engine_browsers, key=lambda b: b.load)

    def _ensure_lifecycle_loop(self) -> None:
        """Start the lifecycle background loop if not already running."""
        if self._lifecycle_task is not None and not self._lifecycle_task.done():
            return
        self._lifecycle_task = asyncio.create_task(self._lifecycle_loop())

    async def _lifecycle_loop(self) -> None:
        """Background loop: health-check crashed browsers and evict idle ones.

        Runs every 30 seconds. Exits automatically when the pool is empty.
        Health checks are performed outside the lock to avoid blocking acquire/release.
        """
        _lifecycle_interval_seconds = 30

        while True:
            await asyncio.sleep(_lifecycle_interval_seconds)

            if not self._browsers:
                logger.debug("Lifecycle loop: pool empty, stopping")
                return

            try:
                await self._lifecycle_tick()
                if self._proxy_pool:
                    self._proxy_pool.cleanup_expired_sessions()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Lifecycle loop: unexpected error in tick, will retry next cycle")

    async def _close_browser_instance(self, browser_inst: BrowserInstance) -> None:
        """Close a specific browser instance and its contexts.

        Includes a fallback to force kill the process if graceful close fails.
        """
        for _ctx_key, pool in browser_inst.page_pools.items():
            with contextlib.suppress(Exception):
                await pool.shutdown()

        for _ctx_key, context in browser_inst.contexts.items():
            with contextlib.suppress(Exception):
                await context.close()

        if browser_inst.is_managed:
            try:
                # Try graceful close first with a timeout
                await asyncio.wait_for(browser_inst.browser.close(), timeout=5.0)
            except Exception as e:
                logger.warning(f"Graceful browser close failed or timed out: {e}. Falling back to force kill.")
                browser_inst.force_kill()

    async def shutdown(self) -> None:
        """Close all resources (called at app shutdown)."""
        logger.info(
            f"GlobalBrowserPool shutdown — stats: acquires={self._total_acquires}, "
            f"releases={self._total_releases}, browsers={len(self._browsers)}",
        )

        if self._lifecycle_task and not self._lifecycle_task.done():
            self._lifecycle_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._lifecycle_task
            self._lifecycle_task = None

        async with self._lock:
            for browser_inst in self._browsers:
                # Use our new robust close method instead of direct close
                await self._close_browser_instance(browser_inst)

            self._browsers.clear()

            for launcher in self._launchers.values():
                await launcher.shutdown()
            self._launchers.clear()

        logger.info("GlobalBrowserPool shutdown completed")

    @property
    def config(self) -> BrowserPoolConfig:
        """Get browser pool configuration."""
        return self._config

    @property
    def throttle_strategy(self) -> ThrottleStrategy:
        """Get rate-limiting strategy (used by Navigator)."""
        return self._throttle_strategy

    @property
    def circuit_breaker(self) -> CircuitBreaker | None:
        """Get circuit breaker (used by Navigator)."""
        return self._circuit_breaker

    @property
    def stats(self) -> dict[str, object]:
        """Get global statistics (for monitoring)."""
        current_in_use = self._current_pages_in_use
        available = self._config.max_concurrent_pages - current_in_use
        now = time.monotonic()
        browsers_snapshot = self._browsers
        return {
            "total_browsers": len(browsers_snapshot),
            "external_browsers": sum(1 for b in browsers_snapshot if not b.is_managed),
            "total_contexts": sum(len(b.contexts) for b in browsers_snapshot),
            "total_load": sum(b.load for b in browsers_snapshot),
            "total_acquires": self._total_acquires,
            "total_releases": self._total_releases,
            "current_pages_in_use": current_in_use,
            "available_slots": available,
            "max_concurrent_pages": self._config.max_concurrent_pages,
            "launch_mode": self._config.launch_mode.value,
            "utilization_percent": round(current_in_use / self._config.max_concurrent_pages * 100, 2),
            "lifecycle_active": self._lifecycle_task is not None and not self._lifecycle_task.done(),
            "idle_timeout_seconds": self._config.idle_timeout_seconds,
            "crash_count_browser": self._crash_count_browser,
            "crash_count_page": self._crash_count_page,
            "browsers": [
                {
                    "load": b.load,
                    "contexts": len(b.contexts),
                    "idle_seconds": round(now - b.last_active_at, 1),
                    "is_managed": b.is_managed,
                    "pools": {k: v.stats for k, v in b.page_pools.items()},
                }
                for b in browsers_snapshot
            ],
            "circuit_breaker": self._circuit_breaker.stats if self._circuit_breaker else {},
            "proxy_pool_active_sessions": self._proxy_pool.active_session_count if self._proxy_pool else 0,
        }

    async def health(self) -> dict[str, object]:
        """Get runtime health status for monitoring and diagnostics.

        Returns:
            Health status dictionary with:
            - status: "healthy" | "degraded" | "unhealthy"
            - pool: Current pool statistics
            - browsers_alive: Number of browsers with successful version() call
            - browsers_total: Total number of browser instances
            - memory: Current memory usage (if psutil available)
            - issues: List of detected issues
        """
        issues: list[str] = []

        pool_stats = self.stats
        utilization = float(pool_stats["utilization_percent"])

        if utilization > 90:
            issues.append(f"High utilization: {utilization:.0f}%")

        cb_stats = pool_stats.get("circuit_breaker", {})
        if isinstance(cb_stats, dict) and cb_stats.get("state") == "OPEN":
            issues.append(f"Circuit breaker OPEN (failures: {cb_stats.get('failure_count', 0)})")

        browsers_snapshot = list(self._browsers)
        browsers_total = len(browsers_snapshot)

        async def _probe(index: int, inst: BrowserInstance) -> tuple[int, bool]:
            return index, await self._check_browser_alive(inst)

        results = await asyncio.gather(
            *[_probe(i, b) for i, b in enumerate(browsers_snapshot)],
            return_exceptions=True,
        )

        browsers_alive = 0
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                issues.append(f"Browser #{i} check failed: {type(result).__name__}")
            elif isinstance(result, tuple):
                index, alive = result
                if alive:
                    browsers_alive += 1
                else:
                    issues.append(f"Browser #{index} unresponsive")

        memory_info: dict[str, object] = {}
        try:
            import psutil

            mem = psutil.virtual_memory()
            memory_info = {
                "available_gb": round(mem.available / (1024**3), 2),
                "used_percent": mem.percent,
            }
            if mem.available < 1024**3:
                issues.append(f"Low memory: {memory_info['available_gb']} GB available")
        except (ImportError, TypeError):
            pass

        if browsers_alive == 0 and browsers_total > 0:
            status = "unhealthy"
        elif issues:
            status = "degraded"
        else:
            status = "healthy"

        return {
            "status": status,
            "pool": pool_stats,
            "browsers_alive": browsers_alive,
            "browsers_total": browsers_total,
            "crash_count_browser": self._crash_count_browser,
            "crash_count_page": self._crash_count_page,
            "memory": memory_info,
            "issues": issues,
        }
