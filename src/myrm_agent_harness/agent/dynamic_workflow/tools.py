"""SpawnSubagentTool — PTC bridge to the delegate path for Dynamic Workflows.

[INPUT]
- base_agent::BaseAgent (POS: Parent agent with _spawn_child capability)
- dynamic_workflow.store::WorkflowEventStore (POS: L2 persistent cache)
- sub_agents.types::SubagentCatalog, SubagentConfig (POS: Agent configuration)
- utils.runtime.cancellation::CancellationToken

[OUTPUT]
- SpawnSubagentTool: LangChain BaseTool exposed to PTC scripts as myrm_tools.spawn_subagent

[POS]
Bridges the PTC Python script to the Harness delegate path. Each spawn_subagent()
call goes through parent_agent._spawn_child(), inheriting the full tool registry,
catalog config, cancel_token, and budget from the parent agent.
WorkflowEventStore provides L2 persistent caching beyond the delegate's 60s TTL.
"""

from __future__ import annotations

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

    def _run(self, task_id: str, agent_type: str, task_description: str) -> object:
        raise NotImplementedError("SpawnSubagentTool only supports async execution.")

    async def _arun(
        self,
        task_id: str,
        agent_type: str = "generalPurpose",
        task_description: str = "",
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

        from myrm_agent_harness.agent.sub_agents.types import SubagentConfig

        config = None
        if self.catalog:
            config = await self.catalog.resolve(agent_type)
        if not config:
            config = SubagentConfig(
                system_prompt="You are a sub-agent executing a specific task within a Dynamic Workflow.",
                max_spawn_depth=0,
                concurrency_limit=10,
                max_cost_usd=2.0,
                budget_tokens=200_000,
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
            final_result = {
                "success": getattr(result, "success", False),
                "task_id": getattr(result, "task_id", task_id),
                "agent_type": getattr(result, "agent_type", agent_type),
                "result": getattr(result, "result", None),
                "error": getattr(result, "error", None),
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
