"""Tool lifecycle manager.

[INPUT]
- langchain_core.tools::BaseTool (POS: tools to manage)
- langchain_core.runnables::RunnableConfig (POS: runtime context)
- .lifecycle_protocol::LifecycleAwareTool (POS: protocol for lifecycle tools)

[OUTPUT]
- ToolLifecycleManager: Manages tool initialization and cleanup

[POS]
Orchestrates tool lifecycle: initialize_tools() -> cleanup_tools()
Implements best-effort cleanup, rollback on init failure, and thread-safe operations.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


class ToolLifecycleManager:
    """Manages tool lifecycle (initialization and cleanup).

    Design features:
    - Best-effort cleanup: Failures logged but don't crash the agent
    - Rollback on init failure: Cleans up already-initialized tools
    - Thread-safe: Uses asyncio.Lock to prevent concurrent cleanup
    - Reverse cleanup order: Cleans up in reverse order of initialization

    Usage:
        manager = ToolLifecycleManager()

        # Initialize tools
        await manager.initialize_tools(tools, config)

        # Cleanup tools (on agent shutdown)
        await manager.cleanup_tools(tools)
    """

    def __init__(self, cleanup_timeout: float = 30.0) -> None:
        """Initialize lifecycle manager.

        Args:
            cleanup_timeout: Maximum seconds to wait for tool cleanup (default: 30.0)
        """
        self._cleanup_lock = asyncio.Lock()
        self._initialized: set[str] = set()
        self._cleanup_timeout = cleanup_timeout

    async def initialize_tools(self, tools: list[BaseTool], config: RunnableConfig) -> None:
        """Initialize all lifecycle-aware tools.

        Args:
            tools: List of tools to initialize
            config: Runtime config (contains user_id, session_id, etc.)

        Raises:
            Exception: If any tool initialization fails

        Note:
            - Only tools with ainit() method are initialized
            - On failure, already-initialized tools are cleaned up (rollback)
            - Initialization order matches tool list order
        """
        initialized_tools: list[BaseTool] = []

        try:
            for tool in tools:
                # Skip tools that are already initialized (idempotent behavior)
                if tool.name in self._initialized:
                    logger.debug(" [Lifecycle] Tool already initialized, skipping: %s", tool.name)
                    continue

                if hasattr(tool, "ainit"):
                    try:
                        logger.info(" [Lifecycle] Initializing tool: %s", tool.name)
                        await tool.ainit(config)  # type: ignore[attr-defined]
                        initialized_tools.append(tool)
                        self._initialized.add(tool.name)
                        logger.info(" [Lifecycle] Tool initialized: %s", tool.name)
                    except Exception:
                        logger.exception(" [Lifecycle] Tool init failed: %s", tool.name)
                        raise  # Propagate to trigger rollback

        except Exception:
            # Rollback: cleanup already-initialized tools
            logger.warning(" [Lifecycle] Init failed, rolling back %d initialized tools", len(initialized_tools))
            await self._cleanup_tools_internal(initialized_tools, is_rollback=True)
            raise

    async def cleanup_tools(self, tools: list[BaseTool]) -> None:
        """Cleanup all lifecycle-aware tools (best-effort).

        Args:
            tools: List of tools to cleanup

        Note:
            - Thread-safe: Uses asyncio.Lock
            - Best-effort: Cleanup failures are logged but don't crash
            - Reverse order: Cleans up in reverse order of initialization
            - Idempotent: Can be called multiple times safely
        """
        async with self._cleanup_lock:
            await self._cleanup_tools_internal(tools, is_rollback=False)

    async def _cleanup_tools_internal(self, tools: list[BaseTool], is_rollback: bool) -> None:
        """Internal cleanup implementation.

        Args:
            tools: Tools to cleanup
            is_rollback: Whether this is a rollback (affects logging)
        """
        # Reverse cleanup order to avoid dependency issues
        for tool in reversed(tools):
            if tool.name not in self._initialized:
                continue  # Skip non-initialized tools

            if not hasattr(tool, "acleanup"):
                continue  # Skip tools without cleanup method

            try:
                log_prefix = " [Rollback]" if is_rollback else " [Cleanup]"
                logger.info("%s Cleaning up tool: %s", log_prefix, tool.name)

                # Apply timeout to prevent cleanup from hanging
                try:
                    await asyncio.wait_for(
                        tool.acleanup(),  # type: ignore[attr-defined]
                        timeout=self._cleanup_timeout,
                    )
                except TimeoutError:
                    logger.error("%s Tool cleanup timeout (%.1fs): %s", log_prefix, self._cleanup_timeout, tool.name)
                    # Continue cleanup for other tools despite timeout

                self._initialized.discard(tool.name)
                logger.info("%s Tool cleaned up: %s", log_prefix, tool.name)
            except Exception:
                # Best-effort: log but continue cleanup for other tools
                log_fn = logger.exception if is_rollback else logger.warning
                log_fn("%s Tool cleanup failed (non-blocking): %s", log_prefix, tool.name)
