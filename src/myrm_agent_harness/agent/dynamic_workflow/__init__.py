import asyncio
import uuid
from collections.abc import AsyncIterable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from myrm_agent_harness.agent.streaming.stream_buffer import CancellationToken
from myrm_agent_harness.agent.dynamic_workflow.store import WorkflowEventStore
from myrm_agent_harness.agent.dynamic_workflow.tools import SpawnSubagentTool
from myrm_agent_harness.agent.sub_agents.manager import SubagentManager

# The prompt that instructs the LLM to write the orchestration script
ORCHESTRATOR_PROMPT = """
You are a Dynamic Workflow Orchestrator. Your task is to solve the user's complex request by writing a Python script that orchestrates multiple sub-agents.

You have access to a special Python module called `myrm_tools`.
It contains a function: `myrm_tools.spawn_subagent(task_id: str, agent_type: str, task_description: str) -> dict`

This function spawns a sub-agent and blocks until it completes.
To achieve massive parallelism, you MUST use `concurrent.futures.ThreadPoolExecutor` to call `myrm_tools.spawn_subagent` concurrently.

Example Script:
```python
import concurrent.futures
import myrm_tools
import json

def run_task(task_id, description):
    print(f"Starting {task_id}...")
    result = myrm_tools.spawn_subagent(
        task_id=task_id,
        agent_type="generalPurpose",
        task_description=description
    )
    print(f"Finished {task_id}.")
    return result

tasks = [
    ("task_1", "Analyze the frontend codebase for authentication logic."),
    ("task_2", "Analyze the backend codebase for authentication logic.")
]

with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(run_task, tid, desc) for tid, desc in tasks]
    results = [f.result() for f in concurrent.futures.as_completed(futures)]

print("All tasks completed. Aggregating results...")
# ... process results ...
print(json.dumps(results, indent=2))
```

Write ONLY the Python script. Do not include markdown formatting or explanations. The script will be executed in a secure sandbox.
"""

async def run_dynamic_workflow_stream(
    llm: BaseChatModel,
    query: str,
    chat_history: list[BaseMessage],
    cancel_token: CancellationToken | None = None,
) -> AsyncIterable[dict[str, object]]:
    """
    The core Dynamic Workflow Engine.
    """
    workflow_id = f"wf_{uuid.uuid4().hex[:8]}"
    
    yield {
        "type": "status",
        "step_key": "workflow_init",
        "status": "in_progress",
        "data": {"message": "Initializing Dynamic Workflow Engine..."},
    }
    
    # 1. Initialize Event Store and Subagent Manager
    store = WorkflowEventStore(".myrm/workflow_events.db")
    manager = SubagentManager() # Note: In a real app, this might need proper DI
    
    # Create the tool that will be injected into PTC
    spawn_tool = SpawnSubagentTool(
        manager=manager,
        tool_registry_getter=lambda: [], # We can inject more tools later
        workflow_id=workflow_id,
        store=store,
    )
    
    yield {
        "type": "status",
        "step_key": "workflow_init",
        "status": "success",
        "data": {"message": "Engine initialized with Durable Execution (SQLite)."},
    }
    
    # 2. Generate the Orchestration Script
    yield {
        "type": "status",
        "step_key": "workflow_planning",
        "status": "in_progress",
        "data": {"message": "Generating Python orchestration script..."},
    }
    
    messages = [
        SystemMessage(content=ORCHESTRATOR_PROMPT),
    ] + chat_history + [HumanMessage(content=query)]
    
    response = await llm.ainvoke(messages)
    script_code = response.content
    
    # Clean up markdown if the LLM ignored instructions
    if isinstance(script_code, str):
        if script_code.startswith("```python"):
            script_code = script_code[9:]
        if script_code.startswith("```"):
            script_code = script_code[3:]
        if script_code.endswith("```"):
            script_code = script_code[:-3]
        script_code = script_code.strip()
    
    yield {
        "type": "status",
        "step_key": "workflow_planning",
        "status": "success",
        "data": {"message": "Orchestration script generated."},
    }
    
    # 3. Execute the Script via PTC
    yield {
        "type": "status",
        "step_key": "workflow_execution",
        "status": "in_progress",
        "data": {"message": "Executing workflow (spawning sub-agents)..."},
    }
    
    from myrm_agent_harness.toolkits.code_execution.executors.models import ExecutionContext
    from myrm_agent_harness.toolkits.code_execution.factory import create_executor
    from myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection import inject_ptc_for_python_execution
    
    context = ExecutionContext(
        code=script_code,
        original_code=script_code,
        session_id=workflow_id,
        work_dir="/workspace",
        allow_network=True,
    )
    executor = create_executor()
    
    try:
        result = await inject_ptc_for_python_execution(
            context=context,
            executor=executor,
            ptc_tools=[spawn_tool],
        )
        
        yield {
            "type": "status",
            "step_key": "workflow_execution",
            "status": "success",
            "data": {"message": "Workflow execution completed."},
        }
        
        # Final answer
        yield {
            "type": "content",
            "content": f"Dynamic Workflow `{workflow_id}` executed successfully.\n\nGenerated Script:\n```python\n{script_code}\n```\n\nExecution Output:\n```\n{result.stdout}\n```\n\nExecution Error (if any):\n```\n{result.stderr}\n```",
        }
    except Exception as e:
        yield {
            "type": "status",
            "step_key": "workflow_execution",
            "status": "error",
            "data": {"message": f"Workflow execution failed: {e}"},
        }
        yield {
            "type": "content",
            "content": f"Dynamic Workflow `{workflow_id}` failed to execute.\n\nError:\n```\n{e}\n```",
        }
    
    yield {
        "type": "done",
    }
