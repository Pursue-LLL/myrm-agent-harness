"""Tool lifecycle management protocol.

[INPUT]
- langchain_core.runnables::RunnableConfig (POS: runtime context)

[OUTPUT]
- LifecycleAwareTool: Protocol defining optional ainit/acleanup hooks

[POS]
Defines the protocol for tools that need lifecycle management (init/cleanup).
Tools implementing this protocol can:
- Initialize resources (e.g., connection pools) via ainit()
- Cleanup resources (e.g., close connections) via acleanup()

This is opt-in and non-invasive: existing tools continue to work without modification.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig


class LifecycleAwareTool(Protocol):
    """Protocol for tools that need lifecycle management.

    Tools implementing this protocol can manage resources (e.g., database connections,
    browser sessions, file watchers) across multiple invocations.

    Design principles:
    - Opt-in: Existing tools work without modification
    - Non-invasive: Lifecycle methods are detected via hasattr()
    - Best-effort cleanup: Cleanup failures don't crash the agent

    Usage example:
        class DatabaseQueryTool(BaseTool):
            def __init__(self):
                self._pool = None

            async def ainit(self, config: RunnableConfig):
                user_id = config["configurable"]["context"]["user_id"]
                self._pool = await create_connection_pool(user_id)

            async def acleanup(self):
                if self._pool:
                    await self._pool.close()

            async def _arun(self, query: str, config: RunnableConfig) -> str:
                async with self._pool.acquire() as conn:
                    return await conn.execute(query)
    """

    async def ainit(self, config: RunnableConfig) -> None:
        """Initialize tool resources (called once per agent lifecycle).

        Args:
            config: Runtime config containing user_id, session_id, workspace, etc.
                    Extract context via: config["configurable"]["context"]

        Typical use cases:
            - Create database connection pools
            - Initialize file watchers
            - Start browser sessions
            - Load large models into memory

        Note:
            - This method is called ONCE when the agent first initializes tools
            - Failures will propagate and prevent agent initialization
            - Use this for expensive one-time setup that can be reused
        """
        ...

    async def acleanup(self) -> None:
        """Cleanup tool resources (called on agent shutdown).

        Typical use cases:
            - Close database connection pools
            - Stop file watchers
            - Close browser sessions
            - Release memory/file handles

        Note:
            - This method is called during agent cleanup (best-effort)
            - Failures are logged but don't crash the agent
            - Cleanup is in REVERSE order of initialization
        """
        ...
