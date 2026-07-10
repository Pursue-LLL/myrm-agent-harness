"""Deep Research configuration.

[INPUT]

[OUTPUT]
- DeepResearchPhase: research lifecycle phase enum
- ToolCategory: allowed tool category enum for research agents
- DeepResearchConfig: orchestrator configuration dataclass
- PhaseGuidance: callback return type for cycle-level HITL

[POS]
Configuration and type definitions for the Deep Research system.
Pure data structures with no business logic dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class DeepResearchPhase(StrEnum):
    """Research lifecycle phases (state machine states)."""

    CLARIFY = "clarify"
    PLAN = "plan"
    EXPLORE = "explore"
    RESEARCH = "research"
    REPORT = "report"


class ToolCategory(StrEnum):
    """Tool categories for research agent access control."""

    SEARCH = "search"
    BROWSE = "browse"
    READ = "read"
    CODE_EXEC = "code_exec"
    FILE_WRITE = "file_write"
    MCP = "mcp"


_DEFAULT_TOOL_CATEGORIES: frozenset[ToolCategory] = frozenset(
    {
        ToolCategory.SEARCH,
        ToolCategory.BROWSE,
        ToolCategory.READ,
    }
)


@dataclass(frozen=True, slots=True)
class DeepResearchConfig:
    """Deep Research orchestrator configuration.

    All thresholds are configurable to support Local / SaaS scenarios.
    """

    max_cycles: int = 8
    max_cycles_reasoning: int = 4
    max_duration_seconds: int = 1800
    min_context_tokens: int = 50_000
    max_report_tokens: int = 20_000
    max_concurrent_agents: int = 3
    enable_clarification: bool = True
    report_timeout_seconds: int = 300
    llm_call_timeout_seconds: int = 120
    allowed_tool_categories: frozenset[ToolCategory] = field(default=_DEFAULT_TOOL_CATEGORIES)
    max_research_agent_turns: int = 16
    research_agent_timeout_seconds: int = 600
    max_report_context_chars: int = 100_000
    max_budget_usd: float = 0.0
    budget_warning_threshold: float = 0.8


@dataclass(frozen=True, slots=True)
class PhaseGuidance:
    """Return type for the on_cycle_complete callback.

    Allows the caller to inject guidance into the next research cycle
    or signal early termination.
    """

    guidance: str | None = None
    stop: bool = False


DEFAULT_DEEP_RESEARCH_CONFIG = DeepResearchConfig()
