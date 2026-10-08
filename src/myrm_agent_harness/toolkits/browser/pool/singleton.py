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
import threading
from typing import TYPE_CHECKING

from .browser_pool import GlobalBrowserPool

if TYPE_CHECKING:
    from types import FrameType

    from .config import BrowserPoolConfig
    from .extension_bridge import ExtensionBridge
    from .proxy import ProxyPool

logger = logging.getLogger(__name__)

_global_pool: GlobalBrowserPool | None = None

# Longest an exit hook waits for the pool to close. Closing a healthy pool takes a few seconds
# (each browser gets 5 s to close gracefully before it is force-killed).
_EXIT_SHUTDOWN_DEADLINE_SECONDS = 20.0


def _shutdown_within_deadline(pool: GlobalBrowserPool) -> None:
    """Close the pool on a private event loop without letting a wedged shutdown block process exit.

    Closing a context or browser is an RPC that waits on futures owned by the loop that launched the
    browser. Once that loop is closed (pytest gives every test its own) those futures never resolve, and
    patchright's cancel path waits on them again, so neither a timeout nor a cancellation frees the
    waiter. The work therefore runs on a daemon thread that interpreter exit does not join, and is
    abandoned at the deadline. Browser processes die with their parent; any survivor is swept by the
    orphan cleanup at next start.
    """

    def _run() -> None:
        try:
            asyncio.run(pool.shutdown())
        except Exception:
            logger.warning("GlobalBrowserPool shutdown failed during exit cleanup", exc_info=True)

    worker = threading.Thread(target=_run, name="browser-pool-exit-shutdown", daemon=True)
    worker.start()
    worker.join(_EXIT_SHUTDOWN_DEADLINE_SECONDS)
    if worker.is_alive():
        logger.warning(
            "GlobalBrowserPool shutdown did not finish within %.0fs; abandoning it so the process can exit",
            _EXIT_SHUTDOWN_DEADLINE_SECONDS,
        )


def _cleanup_global_pool() -> None:
    """Graceful shutdown hook for browser pool cleanup.

    Ensures browsers are properly closed on process exit (normal exit, Ctrl+C, SIGTERM) and never
    blocks the exit for longer than ``_EXIT_SHUTDOWN_DEADLINE_SECONDS``.
    """
    pool = _global_pool
    if pool is None:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        loop.create_task(pool.shutdown())
    else:
        _shutdown_within_deadline(pool)


atexit.register(_cleanup_global_pool)

try:
    _original_sigterm = signal.getsignal(signal.SIGTERM)

    def _sigterm_handler(signum: int, frame: FrameType | None) -> None:
        _cleanup_global_pool()
        # SIG_DFL / SIG_IGN are not callable, so only a real previously installed handler is chained.
        if callable(_original_sigterm):
            _original_sigterm(signum, frame)

    signal.signal(signal.SIGTERM, _sigterm_handler)
except ValueError:
    pass


def get_global_browser_pool(
    max_browsers: int = 5,
    launch_options: dict[str, object] | None = None,
    proxy_pool: ProxyPool | None = None,
    config: BrowserPoolConfig | None = None,
    extension_bridge: ExtensionBridge | None = None,
) -> GlobalBrowserPool:
    """Get GlobalBrowserPool singleton.

    First call creates the instance; subsequent calls return the same instance.

    Args:
        max_browsers: Maximum Browser instance count
        launch_options: Patchright launch options (optional)
        proxy_pool: Proxy pool (supports rotation and sticky sessions)
        config: Browser pool config (concurrency/rate-limiting/memory-guard)
        extension_bridge: ExtensionBridge protocol impl for EXTENSION launch mode (injected from business layer)

    Returns:
        GlobalBrowserPool singleton

    """
    global _global_pool

    if _global_pool is None:
        _cleanup_orphan_automation()
        _global_pool = GlobalBrowserPool(
            max_browsers=max_browsers,
            launch_options=launch_options,
            proxy_pool=proxy_pool,
            config=config,
            extension_bridge=extension_bridge,
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


def _cleanup_orphan_automation() -> None:
    """Auto-cleanup orphan automation processes left by a previous abnormal exit."""
    try:
        from ..doctor import cleanup_orphan_processes

        killed = cleanup_orphan_processes(force=True).get("killed", 0)
        if killed:
            logger.warning("Cleaned up %s orphan automation process(es) from previous session", killed)
    except Exception:
        logger.debug("Orphan cleanup skipped (psutil unavailable or scan failed)", exc_info=True)
