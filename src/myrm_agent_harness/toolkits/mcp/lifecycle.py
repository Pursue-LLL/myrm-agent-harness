"""MCP Connection Lifecycle Management.

Provides graceful startup and shutdown hooks to ensure the connection manager
runs correctly within the application lifecycle.

Usage:
    await mcp_lifecycle.startup()
    await mcp_lifecycle.shutdown()

    # or via context manager
    async with mcp_lifecycle_context():
        pass

[INPUT]
- (none)

[OUTPUT]
- MCPLifecycleManager: class — MCP Lifecycle Manager
- mcp_lifecycle_context: function — convenience context manager

[POS]
MCP lifecycle management for connection pool startup/shutdown.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


class MCPLifecycleManager:
    """MCP lifecycle manager.

    Responsibilities:
    - Initialize connection manager on app startup
    - Gracefully close all connections on app shutdown
    - Provide context manager interface
    """

    def __init__(self) -> None:
        self._started = False

    async def startup(self) -> None:
        """Start the MCP connection manager."""
        if self._started:
            logger.warning("[MCPLifecycle] Already started, skipping duplicate init")
            return

        from .connection_manager import get_mcp_connection_manager

        manager = await get_mcp_connection_manager()
        logger.info("[MCPLifecycle] Connection manager started: %s", manager)

        self._started = True

    async def shutdown(self) -> None:
        """Shut down the MCP connection manager if one is live.

        The manager is created lazily on first use and may never go through
        ``startup()``; teardown therefore keys off the live singleton instead of
        this wrapper's flag, and clears it so a later run starts fresh.
        """
        from .connection_manager import MCPConnectionManager

        manager = MCPConnectionManager._instance
        if manager is None:
            return

        await manager.stop()
        logger.info("[MCPLifecycle] Final pool stats: %s", manager.get_stats())
        logger.info("[MCPLifecycle] Connection manager stopped")
        MCPConnectionManager._instance = None
        self._started = False

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        """Lifecycle context manager.

        Usage:
            async with mcp_lifecycle.lifespan():
                # app runs here
                pass
        """
        await self.startup()
        try:
            yield
        finally:
            await self.shutdown()


mcp_lifecycle = MCPLifecycleManager()


@asynccontextmanager
async def mcp_lifecycle_context() -> AsyncIterator[None]:
    """Convenience context manager for MCP lifecycle."""
    async with mcp_lifecycle.lifespan():
        yield
