"""Meta-tools enabling cross-agent mutual observation (inspect) and interactive guidance (instruct).

[INPUT]
- langchain.tools::tool
- pydantic::BaseModel, Field
- session_multiplexer::(AgentSessionMultiplexer, get_session_multiplexer)

[OUTPUT]
- create_inspect_agent_session_tool: LangChain tool for cross-agent inspect inspection.
- create_instruct_agent_tool: LangChain tool for cross-agent interactive instructing.

[POS]
Harness-level tools allowing agents to observe sibling/worker progress and steer executions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain.tools import tool
from pydantic import BaseModel, Field

from myrm_agent_harness.agent.sub_agents.multiplexer.session_multiplexer import (
    AgentSessionMultiplexer,
    get_session_multiplexer,
)

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool


class InspectSessionInput(BaseModel):
    """Input payload for inspect_agent_session."""

    target_session_id: str = Field(
        description="The session_id or task_id of the target agent to inspect."
    )
    tail_lines: int = Field(
        default=30,
        ge=5,
        le=200,
        description="Number of recent execution log lines to retrieve.",
    )


class InstructAgentInput(BaseModel):
    """Input payload for instruct_agent."""

    target_session_id: str = Field(
        description="The session_id or task_id of the recipient agent to instruct."
    )
    instruction: str = Field(
        description="Guidance, clarification, parameter fix, or steering directive to inject.",
        max_length=4000,
    )


def create_inspect_agent_session_tool(
    multiplexer: AgentSessionMultiplexer | None = None,
) -> BaseTool:
    """Create a LangChain tool enabling an agent to inspect another running agent session."""
    mux = multiplexer or get_session_multiplexer()

    @tool(
        "inspect_agent_session",
        description=(
            "Inspect the current status, recent execution logs, and generated artifacts of another "
            "concurrent or headless agent session without interrupting its execution."
        ),
        args_schema=InspectSessionInput,
    )
    def inspect_agent_session_func(
        target_session_id: str,
        tail_lines: int = 30,
    ) -> dict[str, object]:
        snapshot = mux.inspect_session(target_session_id, tail_lines=tail_lines)
        if not snapshot:
            return {
                "success": False,
                "error": f"Session '{target_session_id}' not found in active multiplexer.",
            }

        return {
            "success": True,
            "session_id": snapshot.session_id,
            "agent_type": snapshot.agent_type,
            "state": snapshot.state,
            "is_headless": snapshot.is_headless,
            "task_objective": snapshot.task_objective,
            "log_tail": snapshot.log_tail,
            "artifacts": snapshot.artifacts,
            "pending_instructions_count": snapshot.pending_instructions_count,
            "snapshot_timestamp": snapshot.snapshot_timestamp,
        }

    return inspect_agent_session_func


def create_instruct_agent_tool(
    multiplexer: AgentSessionMultiplexer | None = None,
    current_agent_type: str = "orchestrator",
) -> BaseTool:
    """Create a LangChain tool enabling an agent to steer or provide guidance to another session."""
    mux = multiplexer or get_session_multiplexer()

    @tool(
        "instruct_agent",
        description=(
            "Inject steering instructions, contextual clarifications, or corrections into another "
            "running agent session to help resolve blocks or guide implementation."
        ),
        args_schema=InstructAgentInput,
    )
    def instruct_agent_func(
        target_session_id: str,
        instruction: str,
    ) -> dict[str, object]:
        result = mux.inject_instruction(
            target_session_id,
            instruction,
            source_agent=current_agent_type,
        )
        return {
            "success": result.success,
            "session_id": result.session_id,
            "instruction_id": result.instruction_id,
            "message": result.message,
            "queued_instructions_count": result.queued_instructions_count,
        }

    return instruct_agent_func
