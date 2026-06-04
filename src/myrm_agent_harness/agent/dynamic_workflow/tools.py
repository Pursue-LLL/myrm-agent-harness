from typing import Any, Callable, Optional

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from myrm_agent_harness.agent.sub_agents.manager import SubagentManager
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig
from myrm_agent_harness.agent.dynamic_workflow.store import WorkflowEventStore

class SpawnSubagentInput(BaseModel):
    task_id: str = Field(..., description="Unique identifier for this sub-agent task.")
    agent_type: str = Field(..., description="Type of agent to spawn (e.g., 'generalPurpose', 'shell').")
    task_description: str = Field(..., description="The prompt/task for the sub-agent to execute.")
    # Add other fields as needed, keeping it simple for now

class SpawnSubagentTool(BaseTool):
    name: str = "spawn_subagent"
    description: str = "Spawn a sub-agent to execute a task. This tool blocks until the sub-agent completes."
    args_schema: type[BaseModel] = SpawnSubagentInput
    
    manager: SubagentManager
    tool_registry_getter: Callable[[], list[BaseTool]]
    workflow_id: str
    store: Optional[WorkflowEventStore] = None
    
    def _run(self, task_id: str, agent_type: str, task_description: str) -> Any:
        raise NotImplementedError("SpawnSubagentTool only supports async execution.")
        
    async def _arun(self, task_id: str, agent_type: str, task_description: str) -> Any:
        # 1. Check Event Store for cached result (Durable Execution)
        if self.store:
            cached = self.store.get_cached_result(self.workflow_id, task_id)
            if cached:
                return cached

        # 2. Default config for dynamic workflow sub-agents
        config = SubagentConfig(
            max_depth=2,
            max_concurrent=10,
            max_budget_usd=1.0,
            max_budget_tokens=100000,
        )
        
        # 3. Spawn and wait
        result = await self.manager.spawn_child(
            task_id=task_id,
            agent_type=agent_type,
            task_description=task_description,
            config=config,
            context={},
            tool_registry_getter=self.tool_registry_getter,
            wait=True, # Block until complete
        )
        
        # 4. Format result
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
            
        # 5. Save to Event Store
        if self.store:
            self.store.save_result(
                workflow_id=self.workflow_id,
                task_id=task_id,
                agent_type=agent_type,
                task_description=task_description,
                result=final_result
            )
            
        return final_result
