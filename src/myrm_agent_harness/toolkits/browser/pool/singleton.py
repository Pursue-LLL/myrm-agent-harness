"""Global browser pool singleton management and process cleanup hooks.

[INPUT]
- .browser_pool::GlobalBrowserPool (POS: global browser pool)
- .config::BrowserPoolConfig (POS: browser pool config)
- ..doctor::cleanup_orphan_processes (POS: orphan process cleanup)

[OUTPUT]
- get_global_browser_pool: get global pool singleton
- reset_global_browser_pool_for_tests: shut down and clear pool singleton (test teardown)

[POS]
Manages the GlobalBrowserPool singleton lifecycle, including atexit/SIGTERM cleanup hooks
and automatic cleanup of orphan Chrome processes from previous abnormal exits on startup.
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import signal
from typing import TYPE_CHECKING

from .browser_pool import GlobalBrowserPool

if TYPE_CHECKING:
    from .config import BrowserPoolConfig
    from .proxy import ProxyPool

logger = logging.getLogger(__name__)

_global_pool: GlobalBrowserPool | None = None


def _cleanup_global_pool() -> None:
    """Graceful shutdown hook for browser pool cleanup.

    Ensures browsers are properly closed on process exit (normal exit, Ctrl+C, SIGTERM).
    """
    if _global_pool is None:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        loop.create_task(_global_pool.shutdown())
    else:
        asyncio.run(_global_pool.shutdown())


atexit.register(_cleanup_global_pool)

try:
    _original_sigterm = signal.getsignal(signal.SIGTERM)

    def _sigterm_handler(signum: int, frame: object) -> None:
        _cleanup_global_pool()
        if callable(_original_sigterm) and _original_sigterm not in (signal.SIG_DFL, signal.SIG_IGN):
            _original_sigterm(signum, frame)

    signal.signal(signal.SIGTERM, _sigterm_handler)
except ValueError:
    pass


def get_global_browser_pool(
    max_browsers: int = 5,
    launch_options: dict[str, object] | None = None,
    proxy_pool: ProxyPool | None = None,
    config: BrowserPoolConfig | None = None,
) -> GlobalBrowserPool:
    """GetGlobalBrowser池singleton.

    首次Call时CreateInstance,后续CallReturn同一Instance。

    Args:
        max_browsers: Maximum Browser Instance数
        launch_options: Patchright launch Parameter(optional)
        proxy_pool: Proxy池（Support轮换 and 粘性Session）
        config: Browser池Configure（ContainsConcurrent/限流/内存监控）

    Returns:
        GlobalBrowserPool singleton

    """
    global _global_pool

    if _global_pool is None:
        _cleanup_orphan_chromium()
        _global_pool = GlobalBrowserPool(
            max_browsers=max_browsers,
            launch_options=launch_options,
            proxy_pool=proxy_pool,
            config=config,
        )

    return _global_pool


async def reset_global_browser_pool_for_tests() -> None:
    """Shut down and clear the global pool singleton.

    Intended for pytest teardown between tests. Unlike ``get_global_browser_pool()``,
    this never creates a pool when none exists.
    """
    global _global_pool

    pool = _global_pool
    if pool is None:
        return

    await pool.shutdown()
    _global_pool = None


def _cleanup_orphan_chromium() -> None:
    """Auto-cleanup orphan Chrome processes left by a previous abnormal exit."""
    try:
        from ..doctor import cleanup_orphan_processes, find_orphan_chromium_processes

        orphans = find_orphan_chromium_processes()
        if not orphans:
            return

        result = cleanup_orphan_processes([o["pid"] for o in orphans], force=True)
        killed = result.get("killed", 0)
        logger.warning("Cleaned up %d orphan Chrome process(es) from previous session", killed)
    except Exception:
        logger.debug("Orphan cleanup skipped (psutil unavailable or scan failed)", exc_info=True)
