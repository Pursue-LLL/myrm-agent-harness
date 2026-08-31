"""Dynamic Workflow Engine — LLM-generated Python orchestration with PTC.

[INPUT]
- agent.base_agent::BaseAgent (POS: Parent agent with full tool registry and _spawn_child)
- dynamic_workflow.store::WorkflowEventStore (POS: L2 persistent cache for durability)
- dynamic_workflow.tools::SpawnSubagentTool, NotifyProgressTool, HumanAskTool (POS: PTC bridge tools)
- dynamic_workflow.prompts::ORCHESTRATOR_PROMPT (POS: 编排脚本生成提示词 — 引导 LLM 编写 Python 编排脚本)
- dynamic_workflow.prompts::SUMMARIZATION_PROMPT (POS: 执行结果汇总提示词 — 原始 stdout → 用户 Markdown)
- dynamic_workflow.prompts::_MAX_STDOUT_FOR_SUMMARY (POS: 汇总前 stdout 截断预算)
- dynamic_workflow.llm_query_tool::LlmQueryTool, LlmQueryBatchedTool (POS: PTC lightweight LLM sub-call primitives)
- dynamic_workflow.linter::WorkflowLintReport, lint_workflow_script (POS: Dynamic Workflow AST static analysis and dataflow false-edge linter)
- utils.chat_utils::extract_answer_text (POS: LLM 响应答案提取 — str / block list / think 剥离 / reasoning 回退)
- toolkits.code_execution.ptc::inject_ptc_for_python_execution (POS: Sandbox execution)
- utils.runtime.cancellation::CancellationToken
- dynamic_workflow.preflight::WorkflowPlanReview, WorkflowApprovalGate (POS: Trust-layer preflight)
- agent.sub_agents.types::SubagentCatalog (POS: Catalog protocol for type discovery)

[OUTPUT]
- run_dynamic_workflow_stream: AsyncIterable[dict] yielding AgentEventType-compatible SSE events
- _build_available_types_hint: Generates dynamic agent_type listing for ORCHESTRATOR_PROMPT
- Injects spawn_subagent / notify / human_ask / llm_query / llm_query_batched as PTC runtime tools
- Re-exports: WorkflowPlanReview, WorkflowApprovalGate (from preflight.py)
- Re-exports: ORCHESTRATOR_PROMPT, SUMMARIZATION_PROMPT, _MAX_STDOUT_FOR_SUMMARY (from prompts.py)

[POS]
**DW PTC** orchestration layer (PTC family — see EXECUTION_SYSTEM.md).
Breaks context limits by having the LLM write Python scripts that spawn
sub-agents via Workflow RPC (``ptc/`` inject). Sub-agents inherit the full
tool registry, catalog, and budget from the parent agent through the delegate path.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import AsyncIterable
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from myrm_agent_harness.agent.dynamic_workflow.linter import (
    LintIssue,
    LintSeverity,
    WorkflowLintReport,
    lint_workflow_script,
)
from myrm_agent_harness.agent.dynamic_workflow.llm_query_tool import (
    LlmQueryBatchedTool,
    LlmQueryTool,
)
from myrm_agent_harness.agent.dynamic_workflow.notify_stream import (
    drain_notify_queue_nowait,
    iter_notify_events_while_task_runs,
)
from myrm_agent_harness.agent.dynamic_workflow.preflight import (
    WorkflowApprovalGate,
    WorkflowPlanReview,
    count_llm_query_calls,
    count_spawn_calls,
    estimate_workflow_cost,
    format_plan_preview,
    resume_action,
    strip_script_markdown,
)
from myrm_agent_harness.agent.dynamic_workflow.prompts import (
    _MAX_STDOUT_FOR_SUMMARY,
    ORCHESTRATOR_PROMPT,
    SUMMARIZATION_PROMPT,
)
from myrm_agent_harness.agent.dynamic_workflow.store import WorkflowEventStore
from myrm_agent_harness.agent.dynamic_workflow.template_store import (
    WorkflowTemplateRecord,
    WorkflowTemplateStore,
)
from myrm_agent_harness.agent.dynamic_workflow.template_validation import (
    apply_template_args,
    can_skip_plan_confirm,
)
from myrm_agent_harness.agent.dynamic_workflow.tools import (
    AskGateCallable,
    HumanAskTool,
    NotifyProgressTool,
    SpawnSubagentTool,
    SteerChildTool,
    WorkflowRunGuard,
)
from myrm_agent_harness.utils.chat_utils import extract_answer_text

if TYPE_CHECKING:
    from myrm_agent_harness.agent.base_agent import BaseAgent
    from myrm_agent_harness.agent.sub_agents.types import SubagentCatalog
    from myrm_agent_harness.utils.runtime.cancellation import CancellationToken

logger = logging.getLogger(__name__)


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
    approval_gate: WorkflowApprovalGate | None = None,
    ask_gate: AskGateCallable | None = None,
    resume_value: dict[str, object] | None = None,
    pinned_template_id: str | None = None,
    template_args: dict[str, str] | None = None,
    harness_root: Path | str | None = None,
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
        yield {
            "type": "status",
            "step_key": "workflow_init",
            "status": "error",
            "data": {"message": "Cancelled."},
        }
        yield {
            "type": "message_end",
            "messageId": message_id,
            "usage": {},
            "completion_status": "cancelled",
        }
        return

    from myrm_agent_harness.agent.dynamic_workflow.paths import (
        resolve_workflow_events_db_path,
    )

    workflow_db_path = (
        resolve_workflow_events_db_path(harness_root=harness_root)
        if harness_root is not None
        else resolve_workflow_events_db_path()
    )
    store = WorkflowEventStore(workflow_db_path)
    template_store = WorkflowTemplateStore(workflow_db_path)

    def _tool_registry_getter() -> list[object]:
        return (
            list(parent_agent._cached_tools or parent_agent.user_tools)
            if parent_agent
            else []
        )

    notify_queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    run_guard = WorkflowRunGuard()

    spawn_tool = SpawnSubagentTool(
        parent_agent=parent_agent,
        tool_registry_getter=_tool_registry_getter,
        workflow_id=workflow_id,
        catalog=catalog,
        store=store,
        cancel_token=cancel_token,
        event_queue=notify_queue,
        message_id=message_id,
        run_guard=run_guard,
    )
    notify_tool = NotifyProgressTool(
        event_queue=notify_queue,
        message_id=message_id,
    )
    human_ask_tool = HumanAskTool(
        event_queue=notify_queue,
        message_id=message_id,
        ask_gate_callable=ask_gate,
        cancel_token=cancel_token,
    )
    steer_child_tool = SteerChildTool(
        parent_agent=parent_agent,
    )
    llm_query_tool = LlmQueryTool(
        parent_agent=parent_agent,
        cancel_token=cancel_token,
    )
    llm_query_batched_tool = LlmQueryBatchedTool(
        parent_agent=parent_agent,
        cancel_token=cancel_token,
    )

    yield {
        "type": "status",
        "step_key": "workflow_init",
        "status": "success",
        "data": {
            "message": "Engine initialized with Durable Execution (SQLite).",
            "workflow_id": workflow_id,
        },
    }

    # --- Phase 2: Generate orchestration script (or resume stored script) ---
    if cancel_token and cancel_token.is_cancelled:
        yield {
            "type": "message_end",
            "messageId": message_id,
            "usage": {},
            "completion_status": "cancelled",
        }
        return

    resume_action_val = resume_action(resume_value)
    script_code: str | None = None
    pinned_template: WorkflowTemplateRecord | None = None

    if resume_action_val == "skip":
        yield {
            "type": "message",
            "messageId": message_id,
            "data": "Dynamic Workflow cancelled — orchestration was not approved.",
        }
        yield {
            "type": "message_end",
            "messageId": message_id,
            "usage": {},
            "completion_status": "cancelled",
        }
        return

    if resume_action_val in ("confirm", "edit"):
        script_code = store.get_orchestration_script(workflow_id)
        if script_code is None:
            yield {
                "type": "message",
                "messageId": message_id,
                "data": "Dynamic Workflow resume failed — stored orchestration script not found.",
            }
            yield {
                "type": "message_end",
                "messageId": message_id,
                "usage": {},
                "completion_status": "error",
            }
            return

    if script_code is None and pinned_template_id:
        pinned_template = template_store.get_template(pinned_template_id)
        if pinned_template is None:
            yield {
                "type": "message",
                "messageId": message_id,
                "data": f"Dynamic Workflow template `{pinned_template_id}` was not found.",
            }
            yield {
                "type": "message_end",
                "messageId": message_id,
                "usage": {},
                "completion_status": "error",
            }
            return
        try:
            script_code = apply_template_args(
                pinned_template.script_code, template_args
            )
        except ValueError as exc:
            yield {
                "type": "message",
                "messageId": message_id,
                "data": str(exc),
            }
            yield {
                "type": "message_end",
                "messageId": message_id,
                "usage": {},
                "completion_status": "error",
            }
            return
        yield {
            "type": "status",
            "step_key": "workflow_planning",
            "status": "success",
            "data": {
                "message": f"Loaded workflow template `{pinned_template.display_name}`.",
                "workflow_template_id": pinned_template.template_id,
            },
        }

    if script_code and resume_action_val in ("confirm", "edit"):
        yield {
            "type": "status",
            "step_key": "workflow_planning",
            "status": "success",
            "data": {"message": "Resuming approved orchestration script."},
        }
    elif script_code is None:
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

        messages = [
            SystemMessage(content=orchestrator_prompt),
            *chat_history,
            HumanMessage(content=query),
        ]
        response = await llm.ainvoke(messages)
        raw_script = extract_answer_text(response)
        script_code = strip_script_markdown(raw_script)

        yield {
            "type": "status",
            "step_key": "workflow_planning",
            "status": "success",
            "data": {"message": "Orchestration script generated."},
        }

    assert script_code is not None

    lint_report = lint_workflow_script(script_code, query=query)
    spawn_count = lint_report.spawn_calls_found or count_spawn_calls(script_code)
    llm_query_calls = (
        lint_report.llm_query_calls_found,
        lint_report.llm_query_batched_calls_found,
    )
    if llm_query_calls == (0, 0):
        llm_query_calls = count_llm_query_calls(script_code)

    estimated_cost_usd, remaining_budget_usd, cost_status = (
        await estimate_workflow_cost(
            parent_agent,
            catalog,
            spawn_count,
            query,
            llm_query_calls=llm_query_calls,
        )
    )
    plan_review = WorkflowPlanReview(
        script_code=script_code,
        spawn_count=spawn_count,
        estimated_cost_usd=estimated_cost_usd,
        remaining_budget_usd=remaining_budget_usd,
        cost_status=cost_status,
        llm_query_single_calls=llm_query_calls[0],
        llm_query_batched_calls=llm_query_calls[1],
        lint_report=lint_report,
        goal_brief=lint_report.goal_brief,
    )

    skip_plan_confirm = pinned_template is not None and can_skip_plan_confirm(
        script_code=script_code,
        trust_latch=pinned_template.trust_latch,
        estimated_cost_usd=estimated_cost_usd,
    )
    needs_approval = (
        spawn_count >= 1
        and approval_gate is not None
        and resume_action_val not in ("confirm", "edit")
        and not skip_plan_confirm
    )
    if needs_approval:
        assert approval_gate is not None
        store.save_orchestration_script(workflow_id, script_code)
        yield {
            "type": "status",
            "messageId": message_id,
            "data": {
                "phase": "plan_confirm",
                "status": "waiting",
                "plan": format_plan_preview(plan_review),
                "source": "dynamic_workflow",
                "spawn_count": spawn_count,
                "estimated_cost_usd": estimated_cost_usd,
                "remaining_budget_usd": remaining_budget_usd,
                "cost_status": cost_status,
            },
        }

        approved = await approval_gate(plan_review)
        yield {
            "type": "status",
            "messageId": message_id,
            "data": {
                "phase": "plan_confirm",
                "status": "resolved",
                "modified": False,
                "source": "dynamic_workflow",
            },
        }

        if not approved:
            yield {
                "type": "message",
                "messageId": message_id,
                "data": "Dynamic Workflow cancelled — orchestration was not approved.",
            }
            yield {
                "type": "message_end",
                "messageId": message_id,
                "usage": {},
                "completion_status": "cancelled",
            }
            return

    store.save_orchestration_script(workflow_id, script_code)

    if not lint_report.is_valid:
        yield {
            "type": "message",
            "messageId": message_id,
            "data": f"Dynamic Workflow static verification failed: {lint_report.summary}",
        }
        yield {
            "type": "message_end",
            "messageId": message_id,
            "usage": {},
            "completion_status": "error",
        }
        return

    # --- Phase 3: Execute via PTC ---
    if cancel_token and cancel_token.is_cancelled:
        yield {
            "type": "message_end",
            "messageId": message_id,
            "usage": {},
            "completion_status": "cancelled",
        }
        return

    yield {
        "type": "status",
        "step_key": "workflow_execution",
        "status": "in_progress",
        "data": {"message": "Executing workflow (spawning sub-agents)..."},
    }

    from myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer import (
        set_current_message_id,
    )
    from myrm_agent_harness.agent.sub_agents._workspace_diff import (
        diff_snapshots,
        take_workspace_snapshot,
    )
    from myrm_agent_harness.agent.workspace_coordination.merge.merge_snapshots import (
        build_merge_snapshot_context,
    )
    from myrm_agent_harness.toolkits.code_execution.executors.models import (
        ExecutionContext,
    )
    from myrm_agent_harness.toolkits.code_execution.factory import create_executor
    from myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection import (
        inject_ptc_for_python_execution,
    )
    from myrm_agent_harness.toolkits.code_execution.utils.workspace_path import (
        WorkspacePathResolver,
    )

    set_current_message_id(message_id)
    workspace_root = str(WorkspacePathResolver.resolve_workspace_root())
    pre_workspace_snapshot = take_workspace_snapshot(workspace_root)
    merge_snapshot_ctx = build_merge_snapshot_context(
        session_id=chat_id,
        message_id=message_id,
        workspace_root=workspace_root,
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
    workflow_error: str | None = None
    merge_summary: dict[str, object] | None = None
    merge_error_note = ""
    result = None

    try:
        inject_task = asyncio.create_task(
            inject_ptc_for_python_execution(
                context=context,
                executor=executor,
                ptc_tools=[
                    spawn_tool,
                    notify_tool,
                    human_ask_tool,
                    steer_child_tool,
                    llm_query_tool,
                    llm_query_batched_tool,
                ],
                override_allowed=frozenset(
                    {"spawn_subagent", "notify", "human_ask", "steer_child"}
                ),
            )
        )
        async for notify_event in iter_notify_events_while_task_runs(
            notify_queue, inject_task, cancel_token=cancel_token
        ):
            yield notify_event
        result = await inject_task
        if result is not None and not result.success:
            workflow_failed = True
            workflow_error = (
                result.error or result.stderr or "Dynamic Workflow PTC execution failed"
            )

    except Exception as e:
        workflow_failed = True
        workflow_error = f"{type(e).__name__}: {e}"
        for notify_event in await drain_notify_queue_nowait(notify_queue):
            yield notify_event
        logger.error("Dynamic Workflow execution failed: %s", e, exc_info=True)
    finally:
        merge_results = run_guard.merge_results
        if merge_results:
            from myrm_agent_harness.agent.sub_agents.spawn_prep import (
                spawn_result_for_store_after_merge,
            )
            from myrm_agent_harness.agent.workspace_coordination.merge.batch_merge import (
                merge_batch_workspace_sync_backs,
            )

            merge_summary = await merge_batch_workspace_sync_backs(
                merge_results,
                snapshot_context=merge_snapshot_ctx,
            )
            logger.info(
                "DW parallel workspace merge: workflow=%s summary=%s",
                workflow_id,
                merge_summary,
            )
            for item in merge_results:
                task_id_val = item.get("task_id")
                if (
                    isinstance(task_id_val, str)
                    and item.get("workspace_merge_status") == "merged"
                ):
                    store.update_stored_result(
                        workflow_id,
                        task_id_val,
                        spawn_result_for_store_after_merge(item),
                    )
            if not merge_summary.get("workspace_merge_ok", True):
                errors = merge_summary.get("workspace_merge_errors", [])
                if isinstance(errors, list) and errors:
                    merge_error_note = "Workspace merge errors:\n" + "\n".join(
                        str(item) for item in errors
                    )

    exec_status = "success"
    exec_message = "Workflow execution completed."
    if merge_summary is not None and not merge_summary.get("workspace_merge_ok", True):
        exec_status = "warning"
        exec_message = "Workflow execution completed with workspace merge warnings."
    if workflow_failed:
        exec_status = "error"
        exec_message = f"Workflow execution failed: {workflow_error}"

    yield {
        "type": "status",
        "step_key": "workflow_execution",
        "status": exec_status,
        "data": {"message": exec_message},
    }

    if workflow_failed:
        failure_body = (
            f"Dynamic Workflow `{workflow_id}` failed.\n\n**Error:** {workflow_error}"
        )
        if merge_error_note:
            failure_body += f"\n\n{merge_error_note}"
        yield {
            "type": "message",
            "messageId": message_id,
            "data": failure_body,
        }
        yield {
            "type": "message_end",
            "messageId": message_id,
            "usage": {},
            "completion_status": "error",
        }
        return

    # --- Phase 4: Summarize results ---
    if cancel_token and cancel_token.is_cancelled:
        yield {
            "type": "message_end",
            "messageId": message_id,
            "usage": {},
            "completion_status": "cancelled",
        }
        return

    stdout = (result.stdout or "").strip() if result is not None else ""
    stderr = (result.stderr or "").strip() if result is not None else ""
    if merge_error_note:
        stderr = (
            f"{stderr}\n\n{merge_error_note}".strip() if stderr else merge_error_note
        )

    if stdout or stderr:
        truncated = (
            stdout[-_MAX_STDOUT_FOR_SUMMARY:]
            if len(stdout) > _MAX_STDOUT_FOR_SUMMARY
            else stdout
        )
        if len(stdout) > _MAX_STDOUT_FOR_SUMMARY:
            truncated = (
                f"[...truncated {len(stdout) - _MAX_STDOUT_FOR_SUMMARY} chars...]\n"
                + truncated
            )

        summary_input = f"User Request:\n{query}\n\nExecution Output:\n{truncated}"
        if stderr:
            summary_input += f"\n\nExecution Errors:\n{stderr}"

        summary_messages = [
            SystemMessage(content=SUMMARIZATION_PROMPT),
            HumanMessage(content=summary_input),
        ]

        try:
            summary_response = await parent_agent.llm.ainvoke(summary_messages)
            summary_text = extract_answer_text(summary_response)
        except Exception as e:
            logger.warning(
                "Summarization LLM call failed, falling back to raw output: %s", e
            )
            summary_text = f"## Workflow Results\n\n```\n{truncated}\n```"
            if stderr:
                summary_text += f"\n\n### Errors\n```\n{stderr}\n```"
    else:
        summary_text = (
            f"Dynamic Workflow `{workflow_id}` completed but produced no output."
        )

    workspace_diff_text = diff_snapshots(
        pre_workspace_snapshot,
        take_workspace_snapshot(workspace_root),
    )
    if workspace_diff_text:
        summary_text = f"{summary_text.rstrip()}\n\n{workspace_diff_text}"

    yield {
        "type": "message",
        "messageId": message_id,
        "data": summary_text,
    }

    if exec_status == "error":
        completion_status = "error"
    elif exec_status == "warning":
        completion_status = "warning"
    else:
        completion_status = "success"

    yield {
        "type": "message_end",
        "messageId": message_id,
        "usage": {},
        "completion_status": completion_status,
    }
