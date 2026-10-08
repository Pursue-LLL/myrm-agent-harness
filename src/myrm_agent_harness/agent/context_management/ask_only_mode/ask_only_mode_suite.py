"""Suite implementing WorkBuddy Ask-Only mode, dynamic tool filtering and token savings.

[INPUT]
- agent.context_management.ask_only_mode.ask_only_tool_filter::AskOnlyToolFilter (POS: Tool filter and
  execution interceptor enforcing Ask-Only mode boundaries.)
- agent.context_management.ask_only_mode.ask_only_types::AskOnlyFilterResult, SessionInteractionMode,
  ToolDescriptor, ToolExecutionCheckResult, ToolSideEffectLevel (POS: Strongly typed contracts for Ask-Only
  mode tool filtering and execution safety.)

[OUTPUT]
- WorkBuddyAskOnlyModeSuite: Industrial-grade suite for managing Ask-Only mode tool pruning and runtime
  safety.

[POS]
Suite implementing WorkBuddy Ask-Only mode, dynamic tool filtering and token savings.
"""

from __future__ import annotations

from .ask_only_tool_filter import AskOnlyToolFilter
from .ask_only_types import (
    AskOnlyFilterResult,
    SessionInteractionMode,
    ToolDescriptor,
    ToolExecutionCheckResult,
    ToolSideEffectLevel,
)


class WorkBuddyAskOnlyModeSuite:
    """Industrial-grade suite for managing Ask-Only mode tool pruning and runtime safety."""

    def __init__(
        self,
        initial_mode: SessionInteractionMode = SessionInteractionMode.ASK_ONLY,
        tool_filter: AskOnlyToolFilter | None = None,
    ) -> None:
        """Initialize Ask-Only mode suite."""
        self._mode: SessionInteractionMode = initial_mode
        self._filter: AskOnlyToolFilter = tool_filter or AskOnlyToolFilter()
        self._tools: dict[str, ToolDescriptor] = {}
        self._total_blocked_executions: int = 0

    @property
    def current_mode(self) -> SessionInteractionMode:
        """Return active session interaction mode."""
        return self._mode

    @property
    def total_blocked_executions(self) -> int:
        """Return cumulative count of blocked mutation tool executions."""
        return self._total_blocked_executions

    def set_mode(self, mode: SessionInteractionMode) -> None:
        """Switch session interaction mode between Ask-Only and Goal Execution."""
        self._mode = mode

    def register_tool(self, tool: ToolDescriptor) -> None:
        """Register an agent tool into the tool registry."""
        self._tools[tool.name] = tool

    def register_tools(self, tools: list[ToolDescriptor]) -> None:
        """Register a batch of agent tools."""
        for tool in tools:
            self.register_tool(tool)

    def get_registered_tool(self, name: str) -> ToolDescriptor | None:
        """Retrieve tool descriptor by name."""
        return self._tools.get(name)

    def get_active_tools(self) -> list[ToolDescriptor]:
        """Return active tools exposed to model context under current mode."""
        res = self._filter.filter_tools(list(self._tools.values()), self._mode)
        return res.allowed_tools

    def evaluate_filter(self) -> AskOnlyFilterResult:
        """Evaluate and return detailed filtering report and token savings under current mode."""
        return self._filter.filter_tools(list(self._tools.values()), self._mode)

    def check_and_authorize_execution(self, tool_name: str) -> ToolExecutionCheckResult:
        """Check whether a requested tool is permitted to execute under current mode."""
        tool = self._tools.get(tool_name)
        if tool is None:
            return ToolExecutionCheckResult(
                allowed=False,
                tool_name=tool_name,
                side_effect_level=ToolSideEffectLevel.MUTATION_EXECUTE,
                violation_reason=f"Tool '{tool_name}' is not registered in suite.",
            )

        check_res = self._filter.verify_execution(tool, self._mode)
        if not check_res.allowed:
            self._total_blocked_executions += 1

        return check_res
