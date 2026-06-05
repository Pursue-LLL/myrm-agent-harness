from collections.abc import Callable

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from myrm_agent_harness.agent.dynamic_workflow.store import WorkflowEventStore
from myrm_agent_harness.agent.sub_agents.manager import SubagentManager
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig


class SpawnSubagentInput(BaseModel):
    task_id: str = Field(..., description="Unique identifier for this sub-agent task.")
    agent_type: str = Field(..., description="Type of agent to spawn (e.g., 'generalPurpose', 'shell').")
    task_description: str = Field(..., description="The prompt/task for the sub-agent to execute.")

class SpawnSubagentTool(BaseTool):
    name: str = "spawn_subagent"
    description: str = "Spawn a sub-agent to execute a task. This tool blocks until the sub-agent completes."
    args_schema: type[BaseModel] = SpawnSubagentInput

    manager: SubagentManager
    tool_registry_getter: Callable[[], list[BaseTool]]
    workflow_id: str
    store: WorkflowEventStore | None = None

    def _run(self, task_id: str, agent_type: str, task_description: str) -> object:
        raise NotImplementedError("SpawnSubagentTool only supports async execution.")

    async def _arun(self, task_id: str, agent_type: str, task_description: str) -> object:
        if self.store:
            cached = self.store.get_cached_result(self.workflow_id, task_id)
            if cached:
                return cached

        config = SubagentConfig(
            system_prompt="You are a sub-agent executing a specific task.",
            max_spawn_depth=0,
            concurrency_limit=10,
            max_cost_usd=1.0,
            budget_tokens=100000,
        )

        result = await self.manager.spawn_child(
            task_id=task_id,
            agent_type=agent_type,
            task_description=task_description,
            config=config,
            context={},
            tool_registry_getter=self.tool_registry_getter,
            wait=True,
        )

        if isinstance(result, dict):
            final_result = result
        else:
            final_result = {
                "success": result.success,
                "task_id": result.task_id,
                "agent_type": result.agent_type,
                "result": result.result,
                "error": result.error,
            }

        if self.store:
            self.store.save_result(
                workflow_id=self.workflow_id,
                task_id=task_id,
                agent_type=agent_type,
                task_description=task_description,
                result=final_result
            )

        return final_result
