"""Subagent control meta-tool: list, cancel, and steer running subagents.

[INPUT]
- agent.base_agent::BaseAgent (POS: Agent base class with list/cancel/steer child APIs)

[OUTPUT]
- create_subagent_control_tool: Unified LLM tool (action=list|cancel|steer)

[POS]
Subagent runtime observability and control exposed as a single LLM tool surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from langchain.tools import tool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.agent.base_agent import BaseAgent

_MAX_STEER_MESSAGE_CHARS = 4000


def create_subagent_control_tool(parent_agent: BaseAgent) -> BaseTool:
    """Create subagent_control_tool for list/cancel/steer operations."""

    class SubagentControlInput(BaseModel):
        action: Literal["list", "cancel", "steer"] = Field(
            description="Control action: list all subagents, cancel a running subagent, or steer with a corrective message.",
        )
        task_id: str | None = Field(
            default=None,
            description="Required for cancel/steer: the subagent task_id from delegate_task_tool.",
        )
        message: str | None = Field(
            default=None,
            description="Required for steer: corrective message injected at the next turn boundary.",
            max_length=_MAX_STEER_MESSAGE_CHARS,
        )

    @tool(
        "subagent_control_tool",
        description=(
            "Manage subagents at runtime. "
            "action=list returns all subagents with status and results; "
            "action=cancel stops a running subagent; "
            "action=steer injects a corrective message into a running subagent."
        ),
        args_schema=SubagentControlInput,
    )
    async def subagent_control_func(
        action: Literal["list", "cancel", "steer"],
        task_id: str | None = None,
        message: str | None = None,
    ) -> dict[str, Any]:
        if action == "list":
            children = parent_agent.list_children()
            return {
                "total": len(children),
                "running": sum(1 for c in children if c.get("status") == "running"),
                "completed": sum(1 for c in children if c.get("status") != "running"),
                "children": children,
            }

        if not task_id:
            return {
                "success": False,
                "error": "task_id is required for cancel and steer actions.",
            }

        if action == "cancel":
            cancelled = parent_agent.cancel_child(task_id)
            if cancelled:
                return {"success": True, "task_id": task_id, "message": f"Subagent {task_id} cancelled"}
            return {
                "success": False,
                "task_id": task_id,
                "message": f"Could not cancel {task_id} (not found or already done)",
            }

        if action == "steer":
            if not message or not message.strip():
                return {"success": False, "error": "message is required for steer action."}
            steered = parent_agent.steer_child(task_id, message)
            if steered:
                return {"success": True, "task_id": task_id, "message": f"Steering message queued for {task_id}"}
            return {
                "success": False,
                "task_id": task_id,
                "message": f"Could not steer {task_id} (not found or already done)",
            }

        return {"success": False, "error": f"Unknown action: {action}"}

    return subagent_control_func
