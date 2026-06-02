"""Tool Selector for Evolution System

Creates Evolution Agent's tool set with executor passing and smart error handling.
Provides read-only, safe tools for Evolution Agent in all execution modes.

[INPUT]
- toolkits.code_execution::CodeExecutor (POS: Code execution toolkit entry point. Aggregates execution configuration, executor implementations, workspace management, and factory functions for the Agent-in-Sandbox architecture.)
- toolkits.web_search::SearchServiceConfig (POS: Web search toolkit entry point. Aggregates and re-exports search tools, result types, metrics, and error hierarchy for unified import.)

[OUTPUT]
- EvolutionToolConfig: Configuration for Evolution Agent tools.
- create_evolution_tools: Create Evolution Agent's tool set.

[POS]
Tool Selector for Evolution System
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.skills.evolution.execution.tool_wrapper import ToolWrapper

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution import CodeExecutor
    from myrm_agent_harness.toolkits.web_search import SearchServiceConfig

logger = logging.getLogger(__name__)


@dataclass
class EvolutionToolConfig:
    """Configuration for Evolution Agent tools.

    Attributes:
        max_tool_rounds: Maximum agent loop rounds (default: 3, max: 5)
        tool_call_limits: Per-tool call limits (prevents abuse)
        enable_smart_error_handling: Enable smart error messages with suggestions
        enable_grep: Enable grep_tool (code search)
        enable_web_fetch: Enable web_fetch_tool (deep page analysis)
        result_summarization_threshold: Summarize tool results larger than this (default: 200000 chars)
        enable_result_summarization: Enable LLM-based result summarization (default: True)
    """

    max_tool_rounds: int = 3
    tool_call_limits: dict[str, int] | None = None
    enable_smart_error_handling: bool = True
    enable_grep: bool = False
    enable_web_fetch: bool = False
    result_summarization_threshold: int = 200_000
    enable_result_summarization: bool = True

    def __post_init__(self):
        """Set default tool limits if not provided and validate config."""
        if self.tool_call_limits is None:
            self.tool_call_limits = {
                "web_search": 3,  # Max 3 web searches per evolution
                "file_read": 15,  # Max 15 file reads per evolution
                "glob": 5,  # Max 5 glob searches per evolution
                "grep": 5,  # Max 5 grep searches per evolution
                "web_fetch": 2,  # Max 2 web fetches per evolution
            }

        # Validate max_tool_rounds (min: 1, max: 10, warn if > 5)
        if self.max_tool_rounds < 1:
            logger.warning("max_tool_rounds < 1, setting to 1")
            self.max_tool_rounds = 1
        elif self.max_tool_rounds > 10:
            logger.warning("max_tool_rounds > 10, this may be excessive")
        elif self.max_tool_rounds > 5:
            logger.info("max_tool_rounds > 5, ensure you understand the cost implications")

        # Validate result_summarization_threshold (min: 1000 chars)
        if self.result_summarization_threshold < 1000:
            logger.warning(
                "result_summarization_threshold=%d < 1000 chars is too small, setting to 1000",
                self.result_summarization_threshold,
            )
            self.result_summarization_threshold = 1000

        # Check tool_call_limits consistency with max_tool_rounds
        if self.tool_call_limits:
            total_possible_calls = sum(self.tool_call_limits.values())
            if total_possible_calls < self.max_tool_rounds:
                logger.warning(
                    "tool_call_limits total (%d) < max_tool_rounds (%d), "
                    "agent may hit limits before reaching max rounds",
                    total_possible_calls,
                    self.max_tool_rounds,
                )


def create_evolution_tools(
    executor: "CodeExecutor",
    search_service_cfg: "SearchServiceConfig | None" = None,
    config: EvolutionToolConfig | None = None,
) -> list[BaseTool]:
    """Create Evolution Agent's tool set.

    Creates read-only, safe tools for Evolution Agent with:
    - Explicit executor passing (works in background_queue mode)
    - Smart error handling with actionable suggestions
    - Tool call limits (prevents abuse)
    - Security restrictions (read-only, scope-limited)

    Args:
        executor: Executor instance for file operations
        search_service_cfg: Search service configuration (optional; omit to skip web_search)
        config: Optional tool configuration

    Returns:
        List of configured tools
    """
    config = config or EvolutionToolConfig()

    # Import tools
    from myrm_agent_harness.agent.meta_tools.file_ops import create_file_read_tool
    from myrm_agent_harness.agent.meta_tools.file_search import create_glob_tool

    # Create base tools
    base_file_read = create_file_read_tool(skills=None)
    base_glob = create_glob_tool()

    # Wrap tools that need executor
    tools: list[BaseTool] = [
        ToolWrapper(base_file_read, executor, enable_smart_error=config.enable_smart_error_handling),
        ToolWrapper(base_glob, executor, enable_smart_error=config.enable_smart_error_handling),
    ]

    if search_service_cfg is not None:
        from myrm_agent_harness.toolkits import create_web_search_tool

        tools.append(create_web_search_tool(search_service_cfg))

    # Optional: Add grep_tool (code search)
    if config.enable_grep:
        from myrm_agent_harness.agent.meta_tools.file_search import create_grep_tool

        base_grep = create_grep_tool()
        tools.append(ToolWrapper(base_grep, executor, enable_smart_error=config.enable_smart_error_handling))

    # Optional: Add web_fetch_tool (deep page analysis)
    if config.enable_web_fetch:
        from myrm_agent_harness.toolkits import create_web_fetch_tool

        base_web_fetch = create_web_fetch_tool()
        tools.append(base_web_fetch)  # web_fetch doesn't need executor

    logger.info("Created Evolution tool set: %d tools (smart_error=%s)", len(tools), config.enable_smart_error_handling)

    return tools


__all__ = ["EvolutionToolConfig", "create_evolution_tools"]
