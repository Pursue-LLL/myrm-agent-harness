"""Agent-facing LangChain tool for inspecting hindsight failure lessons and pre-execution warnings.

[INPUT]
- toolkits.memory.strategies.hindsight.counterfactual_extractor::CounterfactualRuleExtractor
- toolkits.memory.strategies.hindsight.reflection_buffer::HindsightReflectionBuffer
- toolkits.memory.strategies.hindsight.types::PreExecutionWarning, HindsightRule

[OUTPUT]
- HindsightWarningInspectInput: Pydantic input schema for tool
- create_hindsight_reflection_tool: Factory creating LangChain BaseTool for Agent runtime

[POS]
Agent-facing LangChain tool for inspecting hindsight failure lessons and pre-execution warnings.
"""

from __future__ import annotations

import json

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.memory.strategies.hindsight.reflection_buffer import (
    HindsightReflectionBuffer,
)


class HindsightWarningInspectInput(BaseModel):
    """Input schema for inspecting pre-execution cautionary warnings from failure buffer."""

    task_goal: str = Field(
        description="The planned objective or description of the task to be executed"
    )
    intended_tools: list[str] = Field(
        default_factory=list,
        description="List of tool names planned for invocation (e.g. ['run_command', 'write_to_file'])",
    )
    top_k: int = Field(
        default=3,
        description="Maximum number of relevant cautionary warnings to return",
    )


def create_hindsight_reflection_tool(
    buffer: HindsightReflectionBuffer,
) -> BaseTool:
    """Create a LangChain standard tool allowing agents to query proactive cautionary warnings."""

    @tool("inspect_hindsight_warnings", args_schema=HindsightWarningInspectInput)
    def inspect_hindsight_warnings(
        task_goal: str,
        intended_tools: list[str] | None = None,
        top_k: int = 3,
    ) -> str:
        """Query historical failure experiences and retrieve cautionary pre-execution warnings to prevent repeating mistakes."""
        warnings = buffer.match_warnings(
            task_goal=task_goal,
            intended_tools=intended_tools if intended_tools else None,
            top_k=top_k,
        )

        warnings_data: list[dict[str, str | float]] = []
        for w in warnings:
            warnings_data.append(
                {
                    "rule_id": w.rule_id,
                    "task_pattern": w.task_pattern,
                    "warning_text": w.warning_text,
                    "recommended_action": w.recommended_action,
                    "confidence": round(w.confidence, 2),
                }
            )

        payload = {
            "task_goal": task_goal,
            "total_warnings": len(warnings_data),
            "warnings": warnings_data,
        }
        return json.dumps(payload, ensure_ascii=False)

    return inspect_hindsight_warnings
