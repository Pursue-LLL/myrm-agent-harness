"""Graceful shutdown manager with checkpoint save.

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- signal (POS: Python标准库，信号处理)
- asyncio (POS: Python标准库，异步编程)
- atexit (POS: Python标准库，退出处理)
- typing::Callable (POS: Python类型提示)

[OUTPUT]
- GracefulShutdownManager: Graceful shutdown管理器（单例，处理SIGTERM/SIGINT信号）

[POS]
Graceful shutdown manager. Handles SIGTERM/SIGINT signals, triggers graceful shutdown, and auto-saves checkpoints. Zero-configuration, works out of the box.

"""

from __future__ import annotations

import asyncio
import atexit
import signal
from contextlib import suppress
from typing import TYPE_CHECKING

from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_agent_logger(__name__)


class GracefulShutdownManager:
    """Graceful shutdown manager with checkpoint save.

    Singleton pattern ensures only one instance exists globally.
    Automatically registers SIGTERM/SIGINT handlers when created.
    """

    _instance: GracefulShutdownManager | None = None

    def __init__(self) -> None:
        """Initialize graceful shutdown manager (private, use get_instance())."""
        self._shutdown_event = asyncio.Event()
        self._shutdown_callbacks: list[Callable[[], None]] = []
        self._registered = False

    @classmethod
    def get_instance(cls) -> GracefulShutdownManager:
        """Get singleton instance of GracefulShutdownManager.

        Returns:
            Singleton instance
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register_signals(self) -> None:
        """Register SIGTERM/SIGINT signal handlers (idempotent).

        This method is idempotent - can be called multiple times safely.
        Only registers handlers once.
        """
        if self._registered:
            return

        # Register signal handlers
        # Ignore ValueError: signal only works in main thread of the main interpreter
        with suppress(ValueError):
            signal.signal(signal.SIGTERM, self._handle_signal)
            # signal.signal(signal.SIGINT, self._handle_signal)
        # signal.signal(signal.SIGINT, self._handle_signal)

        # Register atexit handler for cleanup logging
        atexit.register(self._handle_exit)

        self._registered = True
        logger.info(" Graceful shutdown manager registered (SIGTERM/SIGINT)")

    def _handle_signal(self, signum: int, frame: object) -> None:
        """Signal handler: trigger graceful shutdown.

        Args:
            signum: Signal number (SIGTERM=15, SIGINT=2)
            frame: Current stack frame (unused)
        """
        logger.warning(f" Received signal {signum}, initiating graceful shutdown...")
        self._shutdown_event.set()

        # Trigger all registered callbacks (checkpoint save)
        for callback in self._shutdown_callbacks:
            with suppress(Exception):
                callback()

    def _handle_exit(self) -> None:
        """Exit handler: final cleanup logging."""
        if self._shutdown_event.is_set():
            logger.info(" Graceful shutdown completed")

    def register_checkpoint_callback(self, callback: Callable[[], None]) -> None:
        """Register a callback to save checkpoint on shutdown.

        Callbacks are executed in registration order when SIGTERM/SIGINT is received.
        Exception in one callback does not affect others.

        Args:
            callback: Checkpoint save callback (must be synchronous)
        """
        self._shutdown_callbacks.append(callback)
        logger.debug(f"Registered checkpoint callback (total={len(self._shutdown_callbacks)})")

    def is_shutting_down(self) -> bool:
        """Check if graceful shutdown is in progress.

        Returns:
            True if shutdown event is set, False otherwise
        """
        return self._shutdown_event.is_set()

    async def wait_for_shutdown(self) -> None:
        """Wait for shutdown event to be set.

        This can be used by long-running tasks to check for shutdown signal.
        """
        await self._shutdown_event.wait()


# Singleton instance accessor (convenience)
def get_shutdown_manager() -> GracefulShutdownManager:
    """Get singleton instance of GracefulShutdownManager.

    Convenience function for getting the singleton instance.

    Returns:
        Singleton instance
    """
    return GracefulShutdownManager.get_instance()
