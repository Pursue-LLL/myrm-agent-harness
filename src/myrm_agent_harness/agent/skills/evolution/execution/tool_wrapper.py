"""Tool Wrapper for Evolution System

Wraps agent tools with executor passing and smart error handling.
Enables agent tools to work in Evolution Agent's background_queue mode.

[INPUT]
- toolkits.code_execution::CodeExecutor (POS: Code execution toolkit entry point. Aggregates execution configuration, executor implementations, workspace management, and factory functions for the Agent-in-Sandbox architecture.)
- agent.storage::StorageProvider (POS: Planner Storage Adapter)

[OUTPUT]
- ToolWrapper: Wrapper for agent tools with executor passing and smart e...

[POS]
Tool Wrapper for Evolution System
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.skills.evolution.execution.executor_context import ExecutorContextManager

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

    from myrm_agent_harness.toolkits.code_execution import CodeExecutor

logger = logging.getLogger(__name__)


class ToolWrapper:
    """Wrapper for agent tools with executor passing and smart error handling.

    Features:
    - Automatic executor context management
    - Smart error handling with actionable suggestions
    - File path correction and suggestions
    - Common error detection

    Thread Safety:
    - Uses ExecutorContextManager for safe context management
    - Each tool invocation has isolated executor context
    """

    def __init__(self, base_tool: BaseTool, executor: "CodeExecutor", enable_smart_error: bool = True):
        """Initialize tool wrapper.

        Args:
            base_tool: The underlying meta_tool to wrap
            executor: Executor instance to pass to the tool
            enable_smart_error: Enable smart error handling with suggestions
        """
        self.base_tool = base_tool
        self.executor = executor
        self.enable_smart_error = enable_smart_error

        # Preserve tool metadata
        self.name = base_tool.name
        self.description = base_tool.description
        self.args_schema = base_tool.args_schema

    async def ainvoke(self, args: dict[str, Any], config: "RunnableConfig | None" = None) -> str:
        """Invoke tool with automatic executor context.

        Args:
            args: Tool arguments
            config: Optional runnable config

        Returns:
            Tool execution result

        Raises:
            Exception: If tool execution fails and smart_error is disabled
        """
        async with ExecutorContextManager(self.executor):
            try:
                result = await self.base_tool.ainvoke(args, config)
                return result
            except FileNotFoundError as e:
                if self.enable_smart_error:
                    return await self._handle_file_not_found(str(e), args)
                raise
            except PermissionError as e:
                if self.enable_smart_error:
                    return self._handle_permission_error(str(e), args)
                raise
            except Exception as e:
                if self.enable_smart_error:
                    return self._format_error(str(e), args)
                raise

    async def _handle_file_not_found(self, error: str, args: dict) -> str:
        """Handle file not found error with smart suggestions.

        Args:
            error: Original error message
            args: Tool arguments

        Returns:
            Formatted error with actionable suggestions
        """
        # Extract path from args
        paths = args.get("paths", args.get("path", []))
        if isinstance(paths, str):
            paths = [paths]
        if not paths:
            return f"File not found: {error}"

        path_str = paths[0]
        suggestions = []

        # 1. Check for URL mistake
        if path_str.startswith(("http://", "https://")):
            suggestions.append(f" Cannot read URL: {path_str}\n Use web_search_tool or web_fetch_tool instead.")
            return "\n".join(suggestions)

        # 2. Try to find similar paths
        try:
            similar_paths = await self._find_similar_paths(path_str)
            if similar_paths:
                suggestions.append(f"File not found: {path_str}\n Did you mean: {similar_paths[0]}?")
                if len(similar_paths) > 1:
                    suggestions.append(f" Or: {', '.join(similar_paths[1:3])}")
                return "\n".join(suggestions)
        except Exception:
            pass  # Fallback to basic error

        # 3. List parent directory if it exists
        try:
            parent = Path(path_str).parent
            if await self._path_exists(str(parent)):
                files = await self._list_dir(str(parent), limit=5)
                if files:
                    suggestions.append(
                        f"File not found: {path_str}\n Available files in {parent}:\n   {', '.join(files)}"
                    )
                    return "\n".join(suggestions)
        except Exception:
            pass  # Fallback to basic error

        # 4. Basic fallback
        return f"File not found: {path_str}"

    def _handle_permission_error(self, error: str, args: dict) -> str:
        """Handle permission error with suggestions.

        Args:
            error: Original error message
            args: Tool arguments

        Returns:
            Formatted error with suggestions
        """
        paths = args.get("paths", args.get("path", []))
        if isinstance(paths, str):
            paths = [paths]
        path_str = paths[0] if paths else "unknown"

        return (
            f" Permission denied: {path_str}\n"
            f" This file may be protected or require elevated permissions.\n"
            f" Evolution Agent operates in read-only mode for safety."
        )

    def _format_error(self, error: str, args: dict) -> str:
        """Format generic error with context.

        Args:
            error: Original error message
            args: Tool arguments

        Returns:
            Formatted error message
        """
        tool_name = self.base_tool.name
        return f" Error in {tool_name}: {error}\n Check the arguments and try again."

    async def _find_similar_paths(self, path: str, max_results: int = 3) -> list[str]:
        """Find similar paths using fuzzy matching.

        Args:
            path: The target path
            max_results: Maximum number of results

        Returns:
            List of similar paths
        """
        # Simplified implementation - can be enhanced with fuzzy matching
        try:
            parent = Path(path).parent
            target_name = Path(path).name

            if not await self._path_exists(str(parent)):
                return []

            files = await self._list_dir(str(parent), limit=20)

            # Simple substring matching
            similar = [
                f"{parent}/{f}" for f in files if target_name.lower() in f.lower() or f.lower() in target_name.lower()
            ]

            return similar[:max_results]
        except Exception:
            return []

    async def _path_exists(self, path: str) -> bool:
        """Check if path exists using executor.

        Args:
            path: Path to check

        Returns:
            True if path exists
        """
        try:
            from myrm_agent_harness.agent.storage import StorageProvider

            storage: StorageProvider = self.executor.storage
            return await storage.path_exists(path)
        except Exception:
            return False

    async def _list_dir(self, path: str, limit: int = 10) -> list[str]:
        """List directory contents using executor.

        Args:
            path: Directory path
            limit: Maximum number of files to return

        Returns:
            List of filenames
        """
        try:
            from myrm_agent_harness.agent.storage import StorageProvider

            storage: StorageProvider = self.executor.storage
            files = await storage.list_files(path, recursive=False)
            return [Path(f).name for f in files[:limit]]
        except Exception:
            return []


__all__ = ["ToolWrapper"]
