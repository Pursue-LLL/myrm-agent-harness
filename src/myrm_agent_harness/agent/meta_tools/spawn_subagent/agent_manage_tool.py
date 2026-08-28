"""Subagent control meta-tool: list, cancel, steer, and wait running subagents.

[INPUT]
- agent.base_agent::BaseAgent (POS: Agent base class with list/cancel/steer/wait child APIs)

[OUTPUT]
- create_subagent_control_tool: Unified LLM tool (action=list|cancel|steer|wait)

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
    """Create subagent_control_tool for list/cancel/steer/wait operations."""

    class SubagentControlInput(BaseModel):
        action: Literal["list", "cancel", "steer", "wait"] = Field(
            description=(
                "Action to perform on subagents: "
                "'list' (inspect status and results of all subagents), "
                "'wait' (synchronously block until the target task_id finishes or times out), "
                "'cancel' (stop a running subagent), "
                "'steer' (inject a corrective message into a running subagent)."
            ),
        )
        task_id: str | None = Field(
            default=None,
            description="Target subagent task_id from delegate_task_tool (required for 'wait', 'cancel', and 'steer').",
        )
        timeout_seconds: int | None = Field(
            default=None,
            description="Max seconds to block for 'wait' before returning still-running (1-120, default: 30).",
            ge=1,
            le=120,
        )
        message: str | None = Field(
            default=None,
            description="Corrective instruction text to inject at the next turn boundary (required for 'steer').",
            max_length=_MAX_STEER_MESSAGE_CHARS,
        )

    @tool(
        "subagent_control_tool",
        description=(
            "Observe and control subagents at runtime. "
            "Use action='wait' to synchronously await an async background subagent (avoids manual polling loops). "
            "Use action='list' to check overall status, 'cancel' to stop execution, and 'steer' to correct direction."
        ),
        args_schema=SubagentControlInput,
    )
    async def subagent_control_func(
        action: Literal["list", "cancel", "steer", "wait"],
        task_id: str | None = None,
        timeout_seconds: int | None = None,
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
                "error": "task_id is required for cancel, steer, and wait actions.",
            }

        if action == "wait":
            from myrm_agent_harness.agent.sub_agents.types import SubAgentStatus

            timeout = min(timeout_seconds or 30, 120)
            result = await parent_agent.wait_children(
                [task_id],
                min_success_rate=0.0,
                timeout=float(timeout),
            )
            failures = result.get("failures") or []
            results = result.get("results") or []
            if results:
                entry = results[0] if isinstance(results[0], dict) else {}
                entry["success"] = True
                return entry
            if failures:
                entry = failures[0] if isinstance(failures[0], dict) else {}
                if entry.get("status") == SubAgentStatus.PENDING_APPROVAL.value:
                    return {
                        "success": False,
                        "task_id": task_id,
                        "status": SubAgentStatus.PENDING_APPROVAL.value,
                        "message": (
                            "Subagent is waiting for user approval (pending_approval). "
                            "The parent agent must surface this approval to the user."
                        ),
                    }
                if entry.get("still_running"):
                    return {
                        "success": False,
                        "task_id": task_id,
                        "status": SubAgentStatus.TIMED_OUT.value,
                        "still_running": True,
                        "message": (
                            f"Subagent {task_id} still running after {timeout}s. Poll action=list again or wait longer."
                        ),
                    }
                return {
                    "success": False,
                    "task_id": task_id,
                    "error": entry.get("error", "Wait failed"),
                }
            return {
                "success": False,
                "task_id": task_id,
                "error": f"Subagent {task_id} not found",
            }

        if action == "cancel":
            cancelled = parent_agent.cancel_child(task_id)
            if cancelled:
                return {
                    "success": True,
                    "task_id": task_id,
                    "message": f"Subagent {task_id} cancelled",
                }
            return {
                "success": False,
                "task_id": task_id,
                "message": f"Could not cancel {task_id} (not found or already done)",
            }

        if action == "steer":
            if not message or not message.strip():
                return {
                    "success": False,
                    "error": "message is required for steer action.",
                }
            steered = parent_agent.steer_child(task_id, message)
            if steered:
                return {
                    "success": True,
                    "task_id": task_id,
                    "message": f"Steering message queued for {task_id}",
                }
            return {
                "success": False,
                "task_id": task_id,
                "message": f"Could not steer {task_id} (not found or already done)",
            }

        return {
            "success": False,
            "error": (
                f"Unknown action: {action!r}. Supported actions are exactly: list, cancel, steer, wait."
            ),
        }

    return subagent_control_func
