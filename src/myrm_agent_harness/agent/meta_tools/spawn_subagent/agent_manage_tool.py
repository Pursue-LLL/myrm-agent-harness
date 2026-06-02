"""Subagent management meta-tools: list, cancel, and steer running subagents.

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- agent.base_agent::BaseAgent (POS: Agent 基类，提供 list_children / cancel_child / steer_child)

[OUTPUT]
- create_list_subagents_tool: 创建列出子 agent 状态的 LLM 工具
- create_cancel_subagent_tool: 创建取消子 agent 的 LLM 工具
- create_steer_subagent_tool: 创建向运行中子 agent 注入纠偏消息的 LLM 工具

[POS]
Subagent management meta-tool. Provides LLM with runtime observability and control over child agents (list, cancel, steer).

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain.tools import tool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.agent.base_agent import BaseAgent


def create_list_subagents_tool(parent_agent: BaseAgent) -> BaseTool:
    """Create list_subagents_tool for querying child agent status."""

    @tool(
        "list_subagents_tool",
        description=(
            "List all subagents (running/completed) with task_id, status, result, etc. "
            "Use to check async subagent results after they complete. "
            "Completion notifications are auto-injected, but this tool provides "
            "full details including payload and handover state."
        ),
    )
    async def list_subagents_func() -> dict[str, Any]:
        """List all subagent statuses."""
        children = parent_agent.list_children()
        return {
            "total": len(children),
            "running": sum(1 for c in children if c.get("status") == "running"),
            "completed": sum(1 for c in children if c.get("status") != "running"),
            "children": children,
        }

    return list_subagents_func


def create_cancel_subagent_tool(parent_agent: BaseAgent) -> BaseTool:
    """Create cancel_subagent_tool for stopping a running child agent."""

    class CancelInput(BaseModel):
        task_id: str = Field(
            description="The task_id of the subagent to cancel (from delegate_task or list_subagents_tool)"
        )

    @tool(
        "cancel_subagent_tool",
        description=(
            "Cancel a running subagent by task_id. "
            "Returns whether the cancellation was successful. "
            "Only works on currently running subagents."
        ),
        args_schema=CancelInput,
    )
    async def cancel_subagent_func(task_id: str) -> dict[str, Any]:
        """Cancel a running subagent."""
        cancelled = parent_agent.cancel_child(task_id)
        if cancelled:
            return {"success": True, "task_id": task_id, "message": f"Subagent {task_id} cancelled"}
        return {
            "success": False,
            "task_id": task_id,
            "message": f"Could not cancel {task_id} (not found or already done)",
        }

    return cancel_subagent_func


_MAX_STEER_MESSAGE_CHARS = 4000


def create_steer_subagent_tool(parent_agent: BaseAgent) -> BaseTool:
    """Create steer_subagent_tool for injecting a corrective message into a running child agent."""

    class SteerInput(BaseModel):
        task_id: str = Field(description="The task_id of the running subagent to steer")
        message: str = Field(
            description="Corrective message to inject. The subagent will receive this as a new user message.",
            max_length=_MAX_STEER_MESSAGE_CHARS,
        )

    @tool(
        "steer_subagent_tool",
        description=(
            "Send a corrective message to a running subagent. "
            "The message is injected as a HumanMessage at the next turn boundary, "
            "allowing mid-run course correction without killing and respawning. "
            "Only works on currently running subagents."
        ),
        args_schema=SteerInput,
    )
    async def steer_subagent_func(task_id: str, message: str) -> dict[str, Any]:
        """Steer a running subagent with a corrective message."""
        steered = parent_agent.steer_child(task_id, message)
        if steered:
            return {"success": True, "task_id": task_id, "message": f"Steering message queued for {task_id}"}
        return {
            "success": False,
            "task_id": task_id,
            "message": f"Could not steer {task_id} (not found or already done)",
        }

    return steer_subagent_func
