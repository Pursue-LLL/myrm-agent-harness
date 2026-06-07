"""Dynamic Workflow Engine — LLM-generated Python orchestration with PTC.

[INPUT]
- agent.base_agent::BaseAgent (POS: Parent agent with full tool registry and _spawn_child)
- dynamic_workflow.store::WorkflowEventStore (POS: L2 persistent cache for durability)
- dynamic_workflow.tools::SpawnSubagentTool (POS: PTC bridge tool)
- toolkits.code_execution.ptc::inject_ptc_for_python_execution (POS: Sandbox execution)
- utils.runtime.cancellation::CancellationToken
- agent.sub_agents.types::SubagentCatalog (POS: Catalog protocol for type discovery)

[OUTPUT]
- run_dynamic_workflow_stream: AsyncIterable[dict] yielding AgentEventType-compatible SSE events
- _build_available_types_hint: Generates dynamic agent_type listing for ORCHESTRATOR_PROMPT

[POS]
Third-generation orchestration layer. Breaks context limits by having the LLM
write Python scripts that spawn sub-agents via PTC. Sub-agents inherit the full
tool registry, catalog, and budget from the parent agent through the delegate path.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import AsyncIterable
from typing import TYPE_CHECKING

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from myrm_agent_harness.agent.dynamic_workflow.store import WorkflowEventStore
from myrm_agent_harness.agent.dynamic_workflow.tools import (
    NotifyProgressTool,
    SpawnSubagentTool,
)

if TYPE_CHECKING:
    from myrm_agent_harness.agent.base_agent import BaseAgent
    from myrm_agent_harness.agent.sub_agents.types import SubagentCatalog
    from myrm_agent_harness.utils.runtime.cancellation import CancellationToken

logger = logging.getLogger(__name__)

ORCHESTRATOR_PROMPT = """\
You are a Dynamic Workflow Orchestrator. Your task is to solve the user's complex \
request by writing a Python script that orchestrates multiple sub-agents.

You have access to a special Python module called `myrm_tools`.
It contains two functions:

1. `myrm_tools.spawn_subagent(task_id: str, agent_type: str, task_description: str, readonly: bool = False) -> dict`
   Spawns a sub-agent that has access to tools (web search, file operations, code execution, etc.).
   Blocks until the sub-agent completes. Returns dict with keys: success, task_id, agent_type, result, error, status.

2. `myrm_tools.notify(message: str, progress: int = -1, step_index: int = 0, total_steps: int = 0, category: str = '', level: str = 'info') -> dict`
   Reports workflow stage progress to the user interface in real-time.
   Call at the start of each major phase so the user can track progress.

IMPORTANT RULES:
1. Use `concurrent.futures.ThreadPoolExecutor` with max_workers <= 8 for parallelism.
2. Wrap EACH spawn_subagent call in try/except to isolate failures:
   ```
   try:
       result = myrm_tools.spawn_subagent(...)
   except Exception as e:
       result = {"success": False, "error": str(e)}
   ```
3. For simple tasks (web search, data lookup), use agent_type="generalPurpose".
4. Print a final JSON summary with ALL results using: print(json.dumps(results, indent=2, ensure_ascii=False))
5. Do NOT use Date.now(), random(), or any non-deterministic functions.
6. For analysis-only tasks (code review, security audit, scanning, performance analysis), \
pass readonly=True to prevent the sub-agent from modifying files.
7. Call `myrm_tools.notify()` at the start of each major workflow phase. Example: \
`myrm_tools.notify("Phase 1: Collecting data", step_index=1, total_steps=3, category="data")`. \
This keeps the user informed of progress. Do NOT call it for every sub-agent — only for phase transitions.

Example Script:
```python
import concurrent.futures
import myrm_tools
import json

def run_task(task_id, description, readonly=False):
    try:
        result = myrm_tools.spawn_subagent(
            task_id=task_id,
            agent_type="generalPurpose",
            task_description=description,
            readonly=readonly,
        )
    except Exception as e:
        result = {"success": False, "error": str(e)}
    return {"task_id": task_id, **result}

tasks = [
    ("task_1", "Analyze the frontend architecture and list key components.", True),
    ("task_2", "Analyze the backend API endpoints and their patterns.", True),
]

myrm_tools.notify("Analyzing codebase", step_index=1, total_steps=2, category="analysis")

with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
    futures = [executor.submit(run_task, tid, desc, ro) for tid, desc, ro in tasks]
    results = [f.result() for f in concurrent.futures.as_completed(futures)]

myrm_tools.notify("Generating summary", step_index=2, total_steps=2, category="summary")

print(json.dumps(results, indent=2, ensure_ascii=False))
```

Write ONLY the Python script. Do not include markdown formatting or explanations. \
The script will be executed in a secure sandbox."""

SUMMARIZATION_PROMPT = """\
You are summarizing the results of a Dynamic Workflow that executed multiple \
sub-agent tasks in parallel. Based on the execution output below, produce a \
clear, well-organized Markdown summary for the user.

RULES:
- Focus on the actual findings and results, NOT the execution mechanics.
- If tasks failed, briefly note which ones and why.
- Use headers, bullet points, and tables where appropriate.
- Be concise but thorough. Do not omit important findings.
- Write in the same language as the user's original request.

CONFIDENCE CLASSIFICATION:
Prefix each major finding's header with a reliability indicator based on evidence \
in the execution output:
- ✅ **Verified** — backed by tool execution output, test results, \
[Verification: PASS], or command stdout/stderr.
- ⚠️ **Unverified** — based on LLM reasoning or file reading alone, \
without independent execution evidence.
- ❌ **Refuted** — contradicted by execution evidence or [Verification: FAIL].
- 💥 **Failed** — the task itself errored or produced no usable output.
Only apply these labels; do NOT explain the classification system to the user."""

_MAX_STDOUT_FOR_SUMMARY = 32_000


async def _build_available_types_hint(catalog: SubagentCatalog | None) -> str:
    """Build a dynamic hint listing available subagent types for the LLM.

    Uses the SubagentCatalog protocol (which includes YAML presets, JIT configs,
    AND user-defined database agents) when provided. Falls back to the global
    SUBAGENT_CONFIGS registry when catalog is None.
    """
    if catalog is not None:
        available_ids = await catalog.list_available()
        if not available_ids:
            return ""

        lines = ["Available agent_type values (use the exact string):"]
        for type_id in available_ids[:50]:
            cfg = await catalog.resolve(type_id)
            if cfg:
                desc = cfg.description or cfg.display_name or cfg.system_prompt[:80]
                lines.append(f'- "{type_id}": {desc}')
        if len(available_ids) > 50:
            lines.append(f"... and {len(available_ids) - 50} more available.")
        lines.append('- "generalPurpose": General-purpose agent for any task (default)')
        return "\n".join(lines)

    from myrm_agent_harness.agent.sub_agents.registry import SUBAGENT_CONFIGS

    if not SUBAGENT_CONFIGS:
        return ""

    lines = ["Available agent_type values (use the exact string):"]
    for name, config in sorted(SUBAGENT_CONFIGS.items()):
        desc = config.description or name
        lines.append(f'- "{name}": {desc}')
    lines.append('- "generalPurpose": General-purpose agent for any task (default)')

    return "\n".join(lines)


async def run_dynamic_workflow_stream(
    parent_agent: BaseAgent,
    query: str,
    chat_history: list[BaseMessage],
    chat_id: str,
    message_id: str,
    cancel_token: CancellationToken | None = None,
    catalog: SubagentCatalog | None = None,
) -> AsyncIterable[dict[str, object]]:
    """Core Dynamic Workflow Engine with full capability inheritance."""
    hash_input = f"{chat_id}:{message_id}".encode()
    workflow_id = f"wf_{hashlib.md5(hash_input).hexdigest()[:12]}"

    yield {
        "type": "status",
        "step_key": "workflow_init",
        "status": "in_progress",
        "data": {"message": "Initializing Dynamic Workflow Engine..."},
    }

    if cancel_token and cancel_token.is_cancelled:
        yield {"type": "status", "step_key": "workflow_init", "status": "error", "data": {"message": "Cancelled."}}
        yield {"type": "message_end", "messageId": message_id, "usage": {}, "completion_status": "cancelled"}
        return

    store = WorkflowEventStore(".myrm/workflow_events.db")

    def _tool_registry_getter() -> list[object]:
        return list(parent_agent._cached_tools or parent_agent.user_tools) if parent_agent else []

    notify_queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()

    spawn_tool = SpawnSubagentTool(
        parent_agent=parent_agent,
        tool_registry_getter=_tool_registry_getter,
        workflow_id=workflow_id,
        catalog=catalog,
        store=store,
        cancel_token=cancel_token,
    )
    notify_tool = NotifyProgressTool(
        event_queue=notify_queue,
        message_id=message_id,
    )

    yield {
        "type": "status",
        "step_key": "workflow_init",
        "status": "success",
        "data": {"message": "Engine initialized with Durable Execution (SQLite).", "workflow_id": workflow_id},
    }

    # --- Phase 2: Generate orchestration script ---
    if cancel_token and cancel_token.is_cancelled:
        yield {"type": "message_end", "messageId": message_id, "usage": {}, "completion_status": "cancelled"}
        return

    yield {
        "type": "status",
        "step_key": "workflow_planning",
        "status": "in_progress",
        "data": {"message": "Generating orchestration script..."},
    }

    llm = parent_agent.llm

    orchestrator_prompt = ORCHESTRATOR_PROMPT
    available_types = await _build_available_types_hint(catalog)
    if available_types:
        orchestrator_prompt = f"{orchestrator_prompt}\n\n{available_types}"

    messages = [SystemMessage(content=orchestrator_prompt), *chat_history, HumanMessage(content=query)]
    response = await llm.ainvoke(messages)
    script_code = response.content

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

    # --- Phase 3: Execute via PTC ---
    if cancel_token and cancel_token.is_cancelled:
        yield {"type": "message_end", "messageId": message_id, "usage": {}, "completion_status": "cancelled"}
        return

    yield {
        "type": "status",
        "step_key": "workflow_execution",
        "status": "in_progress",
        "data": {"message": "Executing workflow (spawning sub-agents)..."},
    }

    from myrm_agent_harness.toolkits.code_execution.executors.models import ExecutionContext
    from myrm_agent_harness.toolkits.code_execution.factory import create_executor
    from myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection import (
        inject_ptc_for_python_execution,
    )

    context = ExecutionContext(
        code=script_code,
        original_code=script_code,
        session_id=workflow_id,
        work_dir="/workspace",
        allow_network=True,
    )
    executor = create_executor()

    workflow_failed = False
    pending_notify_events: list[dict[str, object]] = []

    async def _drain_notify_queue() -> None:
        """Drain queued notify events into pending list for later yielding."""
        while True:
            try:
                event = notify_queue.get_nowait()
                pending_notify_events.append(event)
            except asyncio.QueueEmpty:
                break

    try:
        result = await inject_ptc_for_python_execution(
            context=context,
            executor=executor,
            ptc_tools=[spawn_tool, notify_tool],
            override_allowed=frozenset({"spawn_subagent", "notify"}),
        )
        await _drain_notify_queue()
        for notify_event in pending_notify_events:
            yield notify_event

        yield {
            "type": "status",
            "step_key": "workflow_execution",
            "status": "success",
            "data": {"message": "Workflow execution completed."},
        }

        # --- Phase 4: Summarize results ---
        if cancel_token and cancel_token.is_cancelled:
            yield {"type": "message_end", "messageId": message_id, "usage": {}, "completion_status": "cancelled"}
            return

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()

        if stdout or stderr:
            truncated = stdout[-_MAX_STDOUT_FOR_SUMMARY:] if len(stdout) > _MAX_STDOUT_FOR_SUMMARY else stdout
            if len(stdout) > _MAX_STDOUT_FOR_SUMMARY:
                truncated = f"[...truncated {len(stdout) - _MAX_STDOUT_FOR_SUMMARY} chars...]\n" + truncated

            summary_input = f"User Request:\n{query}\n\nExecution Output:\n{truncated}"
            if stderr:
                summary_input += f"\n\nExecution Errors:\n{stderr}"

            summary_messages = [
                SystemMessage(content=SUMMARIZATION_PROMPT),
                HumanMessage(content=summary_input),
            ]

            try:
                summary_response = await llm.ainvoke(summary_messages)
                summary_text = (
                    summary_response.content
                    if isinstance(summary_response.content, str)
                    else str(summary_response.content)
                )
            except Exception as e:
                logger.warning("Summarization LLM call failed, falling back to raw output: %s", e)
                summary_text = f"## Workflow Results\n\n```\n{truncated}\n```"
                if stderr:
                    summary_text += f"\n\n### Errors\n```\n{stderr}\n```"
        else:
            summary_text = f"Dynamic Workflow `{workflow_id}` completed but produced no output."

        yield {
            "type": "message",
            "messageId": message_id,
            "data": summary_text,
        }

    except Exception as e:
        workflow_failed = True
        await _drain_notify_queue()
        for notify_event in pending_notify_events:
            yield notify_event
        logger.error("Dynamic Workflow execution failed: %s", e, exc_info=True)
        yield {
            "type": "status",
            "step_key": "workflow_execution",
            "status": "error",
            "data": {"message": f"Workflow execution failed: {e}"},
        }
        yield {
            "type": "message",
            "messageId": message_id,
            "data": f"Dynamic Workflow `{workflow_id}` failed.\n\n**Error:** {e}",
        }

    yield {
        "type": "message_end",
        "messageId": message_id,
        "usage": {},
        "completion_status": "error" if workflow_failed else "success",
    }
