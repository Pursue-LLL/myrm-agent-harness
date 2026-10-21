"""Executor Context Manager for Evolution System

Provides thread-safe temporary executor context management using ContextVar.
Enables Evolution Agent to access executor in background_queue mode.

[INPUT]
- toolkits.code_execution::CodeExecutor (POS: Code execution toolkit entry point. Aggregates execution configuration, executor implementations, workspace management, and factory functions for the Agent-in-Sandbox architecture.)

[OUTPUT]
- ExecutorContextManager: Thread-safe context manager for temporarily setting execu...

[POS]
Executor Context Manager for Evolution System
"""

from contextvars import Token
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution import CodeExecutor

from myrm_agent_harness.toolkits.code_execution.executors.base import _executor_var, set_executor


class ExecutorContextManager:
    """Thread-safe context manager for temporarily setting executor.

    Enables Evolution Agent tools to access executor even when running
    in independent asyncio.Task (e.g., background_queue workers).

    Usage:
        with ExecutorContextManager(executor):
            # Tools can now access executor via require_executor()
            result = await file_read_tool.ainvoke(...)

    Thread Safety:
        - Uses ContextVar.Token mechanism for safe reset
        - Each async task has independent context
        - Concurrent calls do not interfere
    """

    def __init__(self, executor: "CodeExecutor"):
        """Initialize context manager.

        Args:
            executor: The executor instance to temporarily set
        """
        self.executor = executor
        self.token: Token | None = None

    def __enter__(self) -> "ExecutorContextManager":
        """Enter context: set executor in ContextVar.

        Returns:
            self for context manager protocol
        """
        self.token = set_executor(self.executor)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Exit context: restore previous executor state.

        Args:
            exc_type: Exception type (if any)
            exc_val: Exception value (if any)
            exc_tb: Exception traceback (if any)

        Returns:
            False to propagate exceptions
        """
        if self.token:
            _executor_var.reset(self.token)
        return False

    async def __aenter__(self) -> "ExecutorContextManager":
        """Async enter context (delegates to sync version)."""
        return self.__enter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Async exit context (delegates to sync version)."""
        return self.__exit__(exc_type, exc_val, exc_tb)


__all__ = ["ExecutorContextManager"]
