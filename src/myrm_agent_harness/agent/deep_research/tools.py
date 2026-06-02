"""Deep Research orchestrator meta-tools.

[INPUT]

[OUTPUT]
- DISPATCH_TOOL_NAME / THINK_TOOL_NAME / FINALIZE_TOOL_NAME: tool name constants
- build_orchestrator_tools(): factory returning the 3 orchestrator tools

[POS]
Defines the 3 fake/meta tools injected into the orchestrator LLM context.
These tools are never executed by a real runtime — the orchestrator intercepts
their tool_call outputs and drives the state machine transitions.

- dispatch_research: dispatches a research sub-run with a task description
- think: chain-of-thought scratchpad (non-reasoning models only)
- finalize_report: signals the orchestrator to transition to the report phase
"""

from __future__ import annotations

from pydantic import BaseModel, Field

DISPATCH_TOOL_NAME = "dispatch_research"
THINK_TOOL_NAME = "think"
FINALIZE_TOOL_NAME = "finalize_report"


class DispatchResearchInput(BaseModel):
    """Input schema for dispatch_research tool."""

    task: str = Field(
        description=(
            "A detailed 1-2 sentence research task. "
            "Include ALL necessary context — the research agent has "
            "no access to conversation history or the research plan."
        )
    )


class ThinkInput(BaseModel):
    """Input schema for think (chain-of-thought) tool."""

    reasoning: str = Field(
        description=(
            "Deep reasoning about research progress, knowledge gaps, "
            "and next investigation directions. Use paragraphs, not lists."
        )
    )


class FinalizeReportInput(BaseModel):
    """Input schema for finalize_report tool."""

    summary: str = Field(default="", description="Optional brief summary of key findings before report generation.")


def _build_tool_schema(name: str, description: str, input_model: type[BaseModel]) -> dict[str, object]:
    """Build an OpenAI-compatible function tool schema."""
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
    """Build the orchestrator's tool definitions.

    Args:
        include_think: Whether to include the think tool.
                       Set False for reasoning models that have native CoT.
    """
    tools: list[dict[str, object]] = [
        _build_tool_schema(
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
            _build_tool_schema(
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
        _build_tool_schema(
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
