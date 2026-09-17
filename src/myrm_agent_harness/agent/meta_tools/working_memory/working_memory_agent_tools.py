"""Agent working memory meta-tool — autonomous 5-action space workbench control.

[INPUT]
- agent.context_management.working_memory.block::LocalWorkingMemoryBlock (POS: 协程手边工作台核心)
- agent.context_management.working_memory.types::SubtaskStatus (POS: 子任务枚举状态)
- langchain_core.tools::BaseTool, tool (POS: LangChain 工具适配器)
- langchain_core.callbacks.manager::dispatch_custom_event (POS: SSE 事件流中继桥梁)

[OUTPUT]
- create_working_memory_manage_tool: 工厂函数，创建 working_memory_manage_tool

[POS]
- 框架元工具层 (agent/meta_tools/working_memory/)。
- 为大模型提供运行时因果工作台的主动操作能力，打通 Discard 剪枝防线，彻底杜绝死循环试错。
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel, Field
from langchain_core.callbacks.manager import dispatch_custom_event
from langchain_core.tools import BaseTool, tool

from myrm_agent_harness.agent.context_management.working_memory.block import (
    LocalWorkingMemoryBlock,
)
from myrm_agent_harness.agent.context_management.working_memory.types import (
    SubtaskStatus,
)

logger = logging.getLogger(__name__)

_VALID_STATUSES = {
    "pending": SubtaskStatus.PENDING,
    "in_progress": SubtaskStatus.IN_PROGRESS,
    "completed": SubtaskStatus.COMPLETED,
    "failed": SubtaskStatus.FAILED,
    "skipped": SubtaskStatus.SKIPPED,
}


class WorkingMemoryManageInput(BaseModel):
    action: Literal["update_subtask", "discard", "summarize", "set_scratchpad"] = Field(
        description=(
            "Action to perform on working memory:\n"
            "- 'update_subtask': Update step status and progress notes\n"
            "- 'discard': Prune a failed hypothesis and auto-register an avoidance trap\n"
            "- 'summarize': Save a dense stage summary to prevent context decay\n"
            "- 'set_scratchpad': Record a transient key-value memo"
        )
    )
    subtask_id: str | None = Field(
        default=None,
        description="Target subtask ID (e.g. 'step-1') for 'update_subtask' or associated with 'discard'.",
    )
    status: Literal["pending", "in_progress", "completed", "failed", "skipped"] | None = Field(
        default=None,
        description="New status for 'update_subtask' ('pending', 'in_progress', 'completed', 'failed', 'skipped').",
    )
    notes: str | None = Field(
        default=None,
        description="Optional progress or diagnostic notes.",
    )
    target: str | None = Field(
        default=None,
        description="Discarded hypothesis or plan identifier (e.g. 'approach_via_regex').",
    )
    reason: str | None = Field(
        default=None,
        description="Why the hypothesis failed or was discarded.",
    )
    avoidance_rule: str | None = Field(
        default=None,
        description="Specific rule to avoid repeating this failure in subsequent turns.",
    )
    summary: str | None = Field(
        default=None,
        description="Dense textual outcome summary for 'summarize'.",
    )
    key: str | None = Field(
        default=None,
        description="Key for 'set_scratchpad'.",
    )
    value: str | None = Field(
        default=None,
        description="Value for 'set_scratchpad'.",
    )


def create_working_memory_manage_tool() -> BaseTool:
    """Create the working_memory_manage_tool LangChain tool."""

    @tool(
        "working_memory_manage_tool",
        description=(
            "Manage the active working memory board during multi-step execution. "
            "Use this tool to track subtask status, discard failed dead-end approaches "
            "(which automatically builds a preventative trap to stop repetitive mistakes), "
            "condense intermediate findings into summaries, or record transient scratchpad notes."
        ),
        args_schema=WorkingMemoryManageInput,
    )
    def working_memory_manage(
        action: Literal["update_subtask", "discard", "summarize", "set_scratchpad"],
        subtask_id: str | None = None,
        status: Literal["pending", "in_progress", "completed", "failed", "skipped"] | None = None,
        notes: str | None = None,
        target: str | None = None,
        reason: str | None = None,
        avoidance_rule: str | None = None,
        summary: str | None = None,
        key: str | None = None,
        value: str | None = None,
    ) -> str:
        state = LocalWorkingMemoryBlock.get_state()
        if state is None:
            # Auto-initialize an active board if not yet created
            state = LocalWorkingMemoryBlock.initialize(goal="Current execution task")

        try:
            if action == "update_subtask":
                if not subtask_id:
                    return json.dumps({
                        "status": "error",
                        "error": "Missing required 'subtask_id' for 'update_subtask'.",
                        "hint": "Provide a valid subtask_id (e.g. 'step-1').",
                    })
                if not status:
                    return json.dumps({
                        "status": "error",
                        "error": "Missing required 'status' for 'update_subtask'.",
                        "hint": "Choose from 'pending', 'in_progress', 'completed', 'failed', 'skipped'.",
                    })

                parsed_status = _VALID_STATUSES.get(status.lower())
                if parsed_status is None:
                    return json.dumps({
                        "status": "error",
                        "error": f"Invalid status '{status}'.",
                        "valid_options": list(_VALID_STATUSES.keys()),
                    })

                ok = LocalWorkingMemoryBlock.update_subtask(
                    subtask_id=subtask_id,
                    status=parsed_status,
                    notes=notes or "",
                )
                if not ok:
                    # Subtask doesn't exist, auto-create it for tolerance
                    LocalWorkingMemoryBlock.add_subtask(
                        title=notes or f"Task {subtask_id}",
                        subtask_id=subtask_id,
                    )
                    LocalWorkingMemoryBlock.update_subtask(
                        subtask_id=subtask_id,
                        status=parsed_status,
                        notes=notes or "",
                    )

                try:
                    dispatch_custom_event(
                        "working_memory_update",
                        {
                            "action": "update_subtask",
                            "subtask_id": subtask_id,
                            "status": parsed_status.value,
                            "notes": notes,
                        },
                    )
                except Exception as exc:
                    logger.debug("Failed to dispatch working_memory_update event: %s", exc)

                return json.dumps({
                    "status": "success",
                    "action": "update_subtask",
                    "subtask_id": subtask_id,
                    "new_status": parsed_status.value,
                })

            if action == "discard":
                rule = avoidance_rule or reason or f"Avoid failing approach: {target or 'unknown'}"
                fingerprint = target or f"trap_{len(state.traps) + 1}"
                LocalWorkingMemoryBlock.record_trap(
                    fingerprint=fingerprint,
                    avoidance_rule=rule,
                    tool_name="agent_discard",
                )

                if subtask_id:
                    LocalWorkingMemoryBlock.update_subtask(
                        subtask_id=subtask_id,
                        status=SubtaskStatus.FAILED,
                        notes=f"Discarded: {rule}",
                    )

                try:
                    dispatch_custom_event(
                        "working_memory_update",
                        {
                            "action": "discard",
                            "fingerprint": fingerprint,
                            "avoidance_rule": rule,
                            "subtask_id": subtask_id,
                        },
                    )
                except Exception as exc:
                    logger.debug("Failed to dispatch working_memory_update event: %s", exc)

                return json.dumps({
                    "status": "success",
                    "action": "discard",
                    "target": fingerprint,
                    "avoidance_rule": rule,
                    "message": "Hypothesis successfully pruned and registered as an avoidance trap.",
                })

            if action == "summarize":
                if not summary:
                    return json.dumps({
                        "status": "error",
                        "error": "Missing required 'summary' text for 'summarize'.",
                    })

                LocalWorkingMemoryBlock.set_scratchpad("latest_summary", summary)

                try:
                    dispatch_custom_event(
                        "working_memory_update",
                        {
                            "action": "summarize",
                            "summary": summary,
                        },
                    )
                except Exception as exc:
                    logger.debug("Failed to dispatch working_memory_update event: %s", exc)

                return json.dumps({
                    "status": "success",
                    "action": "summarize",
                    "message": "Working memory summary recorded.",
                })

            if action == "set_scratchpad":
                if not key or value is None:
                    return json.dumps({
                        "status": "error",
                        "error": "Both 'key' and 'value' are required for 'set_scratchpad'.",
                    })

                safe_value = value[:2000] if len(value) > 2000 else value
                LocalWorkingMemoryBlock.set_scratchpad(key=key, value=safe_value)
                return json.dumps({
                    "status": "success",
                    "action": "set_scratchpad",
                    "key": key,
                    "truncated": len(value) > 2000,
                })

            return json.dumps({
                "status": "error",
                "error": f"Unsupported action: '{action}'.",
                "valid_actions": ["update_subtask", "discard", "summarize", "set_scratchpad"],
            })

        except Exception as exc:
            logger.exception("Error in working_memory_manage: %s", exc)
            return json.dumps({
                "status": "error",
                "error": f"Failed to execute working_memory_manage: {exc}",
            })

    return working_memory_manage
