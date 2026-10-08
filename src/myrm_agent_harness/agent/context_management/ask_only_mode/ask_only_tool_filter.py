# [INPUT]: SessionInteractionMode, ToolDescriptor, ToolSideEffectLevel, AskOnlyFilterResult, ToolExecutionCheckResult
# [OUTPUT]: AskOnlyToolFilter
# [POS]: agent/context_management/ask_only_mode/ask_only_tool_filter.py

"""Tool filter and execution interceptor enforcing Ask-Only mode boundaries.

[INPUT]
- agent.context_management.ask_only_mode.ask_only_types::AskOnlyFilterResult, SessionInteractionMode,
  ToolDescriptor, ToolExecutionCheckResult, ToolSideEffectLevel (POS: Strongly typed contracts for Ask-Only
  mode tool filtering and execution safety.)

[OUTPUT]
- AskOnlyToolFilter: Filter stripping mutation and execution tools in Ask-Only mode to save tokens and prevent
  errors.

[POS]
Tool filter and execution interceptor enforcing Ask-Only mode boundaries.
"""

from __future__ import annotations

from .ask_only_types import (
    AskOnlyFilterResult,
    SessionInteractionMode,
    ToolDescriptor,
    ToolExecutionCheckResult,
    ToolSideEffectLevel,
)

_MUTATION_LEVELS: frozenset[ToolSideEffectLevel] = frozenset({
    ToolSideEffectLevel.MUTATION_WRITE,
    ToolSideEffectLevel.MUTATION_EXECUTE,
})


class AskOnlyToolFilter:
    """Filter stripping mutation and execution tools in Ask-Only mode to save tokens and prevent errors."""

    def filter_tools(
        self,
        tools: list[ToolDescriptor],
        mode: SessionInteractionMode,
    ) -> AskOnlyFilterResult:
        """Filter tool list according to the active interaction mode."""
        if mode == SessionInteractionMode.GOAL_EXECUTION:
            return AskOnlyFilterResult(
                mode=mode,
                allowed_tools=list(tools),
                filtered_tools=[],
                tokens_saved=0,
                filter_reason="Goal execution mode active: all mutation and execution tools permitted.",
            )

        # Mode is ASK_ONLY: filter out mutation & execution tools
        allowed: list[ToolDescriptor] = []
        filtered: list[ToolDescriptor] = []
        tokens_saved = 0

        for tool in tools:
            if tool.side_effect_level in _MUTATION_LEVELS:
                filtered.append(tool)
                tokens_saved += tool.schema_token_cost
            else:
                allowed.append(tool)

        return AskOnlyFilterResult(
            mode=mode,
            allowed_tools=allowed,
            filtered_tools=filtered,
            tokens_saved=tokens_saved,
            filter_reason=(
                f"Ask-Only mode active: pruned {len(filtered)} mutation/execution tool(s), "
                f"saving {tokens_saved} static schema token(s) and preventing unauthorized writes."
            ),
        )

    def verify_execution(
        self,
        tool: ToolDescriptor,
        mode: SessionInteractionMode,
    ) -> ToolExecutionCheckResult:
        """Verify whether a tool execution is permitted under current interaction mode."""
        if mode == SessionInteractionMode.GOAL_EXECUTION:
            return ToolExecutionCheckResult(
                allowed=True,
                tool_name=tool.name,
                side_effect_level=tool.side_effect_level,
                violation_reason=None,
            )

        if tool.side_effect_level in _MUTATION_LEVELS:
            return ToolExecutionCheckResult(
                allowed=False,
                tool_name=tool.name,
                side_effect_level=tool.side_effect_level,
                violation_reason=(
                    f"Execution blocked: tool '{tool.name}' has side-effect level '{tool.side_effect_level.value}', "
                    f"which is forbidden under Ask-Only mode to prevent accidental modifications."
                ),
            )

        return ToolExecutionCheckResult(
            allowed=True,
            tool_name=tool.name,
            side_effect_level=tool.side_effect_level,
            violation_reason=None,
        )
