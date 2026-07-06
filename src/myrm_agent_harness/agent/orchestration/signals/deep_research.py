"""Deep Research orchestration signals — JSON schemas only, not Action Tools.

[OUTPUT]
- DISPATCH_TOOL_NAME / THINK_TOOL_NAME / FINALIZE_TOOL_NAME: signal name constants
- build_orchestrator_tools(): OpenAI function schemas for DR orchestrator bind_tools

[POS]
Control-plane contracts for Deep Research. The orchestrator intercepts tool_calls
and drives state transitions; no ToolNode execution occurs for these names.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .catalog import (
    DISPATCH_RESEARCH_SIGNAL,
    FINALIZE_REPORT_SIGNAL,
    THINK_SIGNAL,
)

DISPATCH_TOOL_NAME = DISPATCH_RESEARCH_SIGNAL
THINK_TOOL_NAME = THINK_SIGNAL
FINALIZE_TOOL_NAME = FINALIZE_REPORT_SIGNAL


class DispatchResearchInput(BaseModel):
    """Input schema for dispatch_research signal."""

    task: str = Field(
        description=(
            "A detailed 1-2 sentence research task. "
            "Include ALL necessary context — the research agent has "
            "no access to conversation history or the research plan."
        )
    )


class ThinkInput(BaseModel):
    """Input schema for think (chain-of-thought) signal."""

    reasoning: str = Field(
        description=(
            "Deep reasoning about research progress, knowledge gaps, "
            "and next investigation directions. Use paragraphs, not lists."
        )
    )


class FinalizeReportInput(BaseModel):
    """Input schema for finalize_report signal."""

    summary: str = Field(
        default="",
        description="Optional brief summary of key findings before report generation.",
    )


def build_signal_schema(name: str, description: str, input_model: type[BaseModel]) -> dict[str, object]:
    """Build an OpenAI-compatible function schema for orchestration bind_tools."""
    schema = input_model.model_json_schema()
    schema.pop("title", None)
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": schema,
        },
    }


def build_orchestrator_tools(include_think: bool = True) -> list[dict[str, object]]:
    """Build Deep Research orchestrator signal schemas for ``llm.bind_tools()``."""
    tools: list[dict[str, object]] = [
        build_signal_schema(
            DISPATCH_TOOL_NAME,
            (
                "Dispatch a research sub-agent to investigate a specific topic. "
                "Provide a detailed task with all necessary context. "
                "Can be called in parallel for independent tasks (max 3)."
            ),
            DispatchResearchInput,
        ),
    ]

    if include_think:
        tools.append(
            build_signal_schema(
                THINK_TOOL_NAME,
                (
                    "Chain-of-thought reasoning scratchpad. "
                    "Use between research dispatches to evaluate findings, "
                    "identify gaps, and plan next steps. "
                    "NEVER call in parallel with other tools."
                ),
                ThinkInput,
            )
        )

    tools.append(
        build_signal_schema(
            FINALIZE_TOOL_NAME,
            (
                "Signal that research is complete and the final report "
                "should be generated. Call only when all topics are "
                "sufficiently investigated."
            ),
            FinalizeReportInput,
        )
    )

    return tools
