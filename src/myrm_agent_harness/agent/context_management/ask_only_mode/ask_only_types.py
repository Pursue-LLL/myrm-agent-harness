# [INPUT]: None
# [OUTPUT]: SessionInteractionMode, ToolSideEffectLevel, ToolDescriptor, AskOnlyFilterResult, ToolExecutionCheckResult
# [POS]: agent/context_management/ask_only_mode/ask_only_types.py

"""Strongly typed contracts for Ask-Only mode tool filtering and execution safety.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- SessionInteractionMode: Interaction mode governing session execution and tool exposure.
- ToolSideEffectLevel: Side effect classification for registered agent tools.
- ToolDescriptor: Strongly typed metadata descriptor for an agent tool.
- AskOnlyFilterResult: Outcome of filtering tools against the current interaction mode.
- ToolExecutionCheckResult: Verification outcome when a tool execution is requested under current mode.

[POS]
Strongly typed contracts for Ask-Only mode tool filtering and execution safety.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SessionInteractionMode(str, Enum):
    """Interaction mode governing session execution and tool exposure."""

    ASK_ONLY = "ask_only"
    GOAL_EXECUTION = "goal_execution"


class ToolSideEffectLevel(str, Enum):
    """Side effect classification for registered agent tools."""

    READ_ONLY = "read_only"
    SAFE_PROBE = "safe_probe"
    MUTATION_WRITE = "mutation_write"
    MUTATION_EXECUTE = "mutation_execute"


@dataclass(frozen=True)
class ToolDescriptor:
    """Strongly typed metadata descriptor for an agent tool."""

    name: str
    description: str
    side_effect_level: ToolSideEffectLevel
    schema_token_cost: int
    parameters_schema: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AskOnlyFilterResult:
    """Outcome of filtering tools against the current interaction mode."""

    mode: SessionInteractionMode
    allowed_tools: list[ToolDescriptor]
    filtered_tools: list[ToolDescriptor]
    tokens_saved: int
    filter_reason: str


@dataclass(frozen=True)
class ToolExecutionCheckResult:
    """Verification outcome when a tool execution is requested under current mode."""

    allowed: bool
    tool_name: str
    side_effect_level: ToolSideEffectLevel
    violation_reason: str | None = None
