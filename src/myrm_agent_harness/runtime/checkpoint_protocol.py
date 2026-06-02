"""Protocol definition for checkpointer objects.

This module defines the interface contract for checkpoint-related operations,
enabling type-safe dependency injection and IDE support.

[INPUT]
- toolkits.browser.checkpoint::ThreadStoreProtocol (POS: Task-level checkpoint/resume module for the browser toolkit. Fully reuses LangGraph Checkpointer's persistence capabilities, only saves incrementally when Session Vault state changes, supports automatic recovery of incomplete tasks on startup with parallel pre-warming.)

[OUTPUT]
- CheckpointerProtocol: Protocol for checkpointer objects with thread store access.
- CheckpointForkManagerProtocol: Protocol for checkpoint fork operations.

[POS]
Protocol definition for checkpointer objects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.browser.checkpoint import ThreadStoreProtocol


class CheckpointerProtocol(Protocol):
    """Protocol for checkpointer objects with thread store access.

    This protocol defines the minimal interface required for checkpoint operations
    in the cleanup and maintenance functions. Any object implementing this protocol
    can be safely passed to functions expecting a checkpointer.

    Example:
        >>> class MyCheckpointer:
        ...     @property
        ...     def thread_store(self):
        ...         return self._store
        ...
        >>> def cleanup(checkpointer: CheckpointerProtocol | None = None):
        ...     if checkpointer:
        ...         store = checkpointer.thread_store  # Type-safe access

    """

    @property
    def thread_store(self) -> ThreadStoreProtocol:
        """Access to thread store for session activity queries.

        Returns:
            Thread store implementing ThreadStoreProtocol

        """
        ...


class CheckpointForkManagerProtocol(Protocol):
    """Protocol for checkpoint fork operations.

    Enables conversation forking by cloning entire agent checkpoint states
    (messages + agent_state + tool outputs) to new thread_id, preserving
    full execution context.

    Usage:
        >>> manager: CheckpointForkManagerProtocol = get_fork_manager()
        >>> success = await manager.fork_checkpoint(
        ...     source_thread_id="chat-123",
        ...     target_thread_id="chat-456",
        ...     checkpoint_id=None  # Latest checkpoint
        ... )

    """

    async def fork_checkpoint(
        self,
        source_thread_id: str,
        target_thread_id: str,
        checkpoint_id: str | None = None,
    ) -> bool:
        """Fork checkpoint to new thread.

        Args:
            source_thread_id: Source conversation thread ID
            target_thread_id: Target conversation thread ID (must not exist)
            checkpoint_id: Checkpoint ID to fork from (None = latest)

        Returns:
            True if fork succeeded, False if checkpoint not found

        """
        ...

    async def get_fork_parent(self, thread_id: str) -> tuple[str, str] | None:
        """Get fork parent info.

        Args:
            thread_id: Thread ID to query

        Returns:
            (parent_thread_id, fork_checkpoint_id) or None

        """
        ...
