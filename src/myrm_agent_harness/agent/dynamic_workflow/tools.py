"""DW PTC tools — SpawnSubagentTool and NotifyProgressTool for Dynamic Workflows.

[INPUT]
- base_agent::BaseAgent (POS: Parent agent with _spawn_child capability)
- dynamic_workflow.store::WorkflowEventStore (POS: L2 persistent cache)
- sub_agents.types::SubagentCatalog, SubagentConfig, WorkspacePolicy (POS: Agent configuration and workspace isolation)
- utils.runtime.cancellation::CancellationToken

[OUTPUT]
- SpawnSubagentTool: PTC tool exposed as myrm_tools.spawn_subagent
- NotifyProgressTool: PTC tool exposed as myrm_tools.notify — emits workflow stage events to the frontend

[POS]
Bridges the PTC Python script to the Harness delegate path. Each spawn_subagent()
call goes through parent_agent._spawn_child(), inheriting the full tool registry,
catalog config, cancel_token, and budget from the parent agent.
WorkflowEventStore provides L2 persistent caching beyond the delegate's 60s TTL.
NotifyProgressTool provides real-time workflow stage notifications from PTC scripts.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from myrm_agent_harness.agent.dynamic_workflow.store import WorkflowEventStore

logger = logging.getLogger(__name__)


class SpawnSubagentInput(BaseModel):
    task_id: str = Field(..., description="Unique identifier for this sub-agent task.")
    agent_type: str = Field(
        default="generalPurpose",
        description="Type of agent to spawn (e.g., 'generalPurpose', 'shell').",
    )
    task_description: str = Field(..., description="The prompt/task for the sub-agent to execute.")
    readonly: bool = Field(
        default=False,
        description="If true, sub-agent cannot write files or run bash commands. Use for analysis-only tasks.",
    )


class SpawnSubagentTool(BaseTool):
    """PTC tool that spawns sub-agents through the parent agent's delegate path."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "spawn_subagent"
    description: str = "Spawn a sub-agent to execute a task. This tool blocks until the sub-agent completes."
    args_schema: type[BaseModel] = SpawnSubagentInput

    parent_agent: object
    tool_registry_getter: Callable[[], list[object]]
    workflow_id: str
    catalog: object | None = None
    store: WorkflowEventStore | None = None
    cancel_token: object | None = None

    def _run(self, task_id: str, agent_type: str, task_description: str, readonly: bool = False) -> object:
        raise NotImplementedError("SpawnSubagentTool only supports async execution.")

    async def _arun(
        self,
        task_id: str,
        agent_type: str = "generalPurpose",
        task_description: str = "",
        readonly: bool = False,
    ) -> object:
        if self.cancel_token and self.cancel_token.is_cancelled:
            return {
                "success": False,
                "task_id": task_id,
                "agent_type": agent_type,
                "result": None,
                "error": "Workflow cancelled by user.",
            }

        if self.store:
            cached = self.store.get_cached_result(self.workflow_id, task_id)
            if cached:
                logger.info("DW cache hit: workflow=%s task=%s", self.workflow_id, task_id)
                return cached

        from dataclasses import replace

        from myrm_agent_harness.agent.sub_agents.types import SubagentConfig, WorkspacePolicy

        config = None
        if self.catalog:
            config = await self.catalog.resolve(agent_type)
        if not config:
            parent_resolver = getattr(self.parent_agent, "model_resolver", None)
            config = SubagentConfig(
                system_prompt="You are a sub-agent executing a specific task within a Dynamic Workflow.",
                max_spawn_depth=0,
                concurrency_limit=10,
                max_cost_usd=2.0,
                budget_tokens=200_000,
                model_resolver=parent_resolver,
            )

        if readonly:
            _readonly_blocked = frozenset(
                {"write_file", "execute_terminal_command", "bash_run_command", "git_commit"}
            )
            config = replace(
                config,
                workspace_policy=WorkspacePolicy.READ_ONLY_SANDBOX,
                disallowed_tools=config.disallowed_tools | _readonly_blocked,
                system_prompt=config.system_prompt
                + "\n\n[READONLY MODE] You are in read-only mode. You can only read and analyze — do NOT attempt file writes, terminal commands, or git commits.",
            )

        try:
            result = await self.parent_agent._spawn_child(
                task_id=task_id,
                agent_type=agent_type,
                task_description=task_description,
                config=config,
                context={},
                tool_registry_getter=self.tool_registry_getter,
                wait=True,
                cancel_token=self.cancel_token,
            )
        except Exception as e:
            logger.error("DW spawn failed: task=%s error=%s", task_id, e)
            return {
                "success": False,
                "task_id": task_id,
                "agent_type": agent_type,
                "result": None,
                "error": f"{type(e).__name__}: {e}",
            }

        if isinstance(result, dict):
            final_result = result
        else:
            status_val = getattr(result, "status", None)
            final_result = {
                "success": getattr(result, "success", False),
                "task_id": getattr(result, "task_id", task_id),
                "agent_type": getattr(result, "agent_type", agent_type),
                "result": getattr(result, "result", None),
                "error": getattr(result, "error", None),
                "status": status_val.value if hasattr(status_val, "value") else str(status_val or "unknown"),
            }

        if self.store:
            self.store.save_result(
                workflow_id=self.workflow_id,
                task_id=task_id,
                agent_type=agent_type,
                task_description=task_description,
                result=final_result,
            )

        return final_result


# ---------------------------------------------------------------------------
# NotifyProgressTool — real-time workflow stage notifications from PTC scripts
# ---------------------------------------------------------------------------

_VALID_NOTIFY_LEVELS = frozenset({"info", "warn", "alert"})


class NotifyProgressInput(BaseModel):
    message: str = Field(..., description="Status message to display to the user.")
    progress: int = Field(
        default=-1,
        description="Progress percentage (0-100). Use -1 for indeterminate.",
    )
    step_index: int = Field(
        default=0,
        description="Current step number (1-based). 0 if not applicable.",
    )
    total_steps: int = Field(
        default=0,
        description="Total number of steps. 0 if not applicable.",
    )
    category: str = Field(
        default="",
        description="Stage/phase label (e.g. 'data_collection', 'analysis'). Groups related notifications.",
    )
    level: str = Field(
        default="info",
        description="Notification level: 'info' (normal), 'warn' (attention), or 'alert' (critical).",
    )


class NotifyProgressTool(BaseTool):
    """PTC tool that emits real-time workflow stage progress events to the frontend SSE stream."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "notify"
    description: str = (
        "Report workflow stage progress to the user interface. "
        "Call this at the start of each major phase to show real-time progress."
    )
    args_schema: type[BaseModel] = NotifyProgressInput

    event_queue: asyncio.Queue[dict[str, object]]
    message_id: str = ""

    def _run(
        self,
        message: str,
        progress: int = -1,
        step_index: int = 0,
        total_steps: int = 0,
        category: str = "",
        level: str = "info",
    ) -> object:
        raise NotImplementedError("NotifyProgressTool only supports async execution.")

    async def _arun(
        self,
        message: str,
        progress: int = -1,
        step_index: int = 0,
        total_steps: int = 0,
        category: str = "",
        level: str = "info",
    ) -> object:
        validated_level = level if level in _VALID_NOTIFY_LEVELS else "info"
        clamped_progress = max(-1, min(100, progress))

        event: dict[str, object] = {
            "type": "status",
            "step_key": "workflow_stage",
            "messageId": self.message_id,
            "status": "in_progress",
            "data": {
                "message": message[:500],
                "notify_progress": clamped_progress,
                "notify_step_index": max(0, step_index),
                "notify_total_steps": max(0, total_steps),
                "notify_category": category[:100],
                "notify_level": validated_level,
            },
        }
        await self.event_queue.put(event)
        return {"success": True, "message": message[:500]}
