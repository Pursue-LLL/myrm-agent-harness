"""DW PTC tools — SpawnSubagentTool and NotifyProgressTool for Dynamic Workflows.

[INPUT]
- base_agent::BaseAgent (POS: Parent agent with _spawn_child capability)
- agent.sub_agents.orchestrator::run_with_verification (POS: Adversarial worker+verifier retry loop)
- agent.sub_agents.spawn_prep (POS: Shared spawn prep SSOT with delegate path)
- dynamic_workflow.store::WorkflowEventStore (POS: L2 persistent cache)
- dynamic_workflow.spawn_cache::SpawnCacheParams (POS: Cache fingerprint)
- agent.skills.mcp.progress_payload::build_workflow_stage_event (POS: Shared notify field SSOT)
- sub_agents.types::SubagentCatalog, SubagentConfig, WorkspacePolicy (POS: Agent configuration and workspace isolation)
- utils.runtime.cancellation::CancellationToken

[OUTPUT]
- SpawnSubagentTool: PTC tool exposed as myrm_tools.spawn_subagent
- NotifyProgressTool: PTC tool exposed as myrm_tools.notify — emits workflow stage events to the frontend
- HumanAskTool: PTC tool exposed as myrm_tools.human_ask — suspends workflow for mid-run user input / decision
- WorkflowRunGuard: Per-workflow spawn counter, concurrency semaphore, parallel writer tracking

[POS]
Bridges the PTC Python script to the Harness delegate path. spawn_subagent() uses
parent_agent._spawn_child() or run_with_verification() when verification_mode is
adversarial. Shares spawn prep with delegate_task_tool via spawn_prep.py.
WorkflowEventStore provides L2 persistent caching beyond the delegate's 60s TTL.
NotifyProgressTool provides real-time workflow stage notifications from PTC scripts.
HumanAskTool provides mid-run human-in-the-loop gate via PhaseWaiter.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, cast

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from myrm_agent_harness.agent.dynamic_workflow.spawn_cache import SpawnCacheParams
from myrm_agent_harness.agent.dynamic_workflow.store import WorkflowEventStore
from myrm_agent_harness.agent.skills.mcp.progress_payload import (
    build_workflow_stage_event,
    normalize_dw_message,
)
from myrm_agent_harness.agent.sub_agents.spawn_prep import (
    apply_readonly_to_config,
    apply_spawn_workspace_isolation,
    build_child_context_from_parent_agent,
    enforce_spawn_policy_on_config,
    memory_isolation_scope,
    merge_candidate_from_spawn_dict,
    sanitize_spawn_result_for_store,
)

if TYPE_CHECKING:
    from myrm_agent_harness.agent.base_agent import BaseAgent
    from myrm_agent_harness.agent.sub_agents.types import SubagentCatalog
    from myrm_agent_harness.utils.runtime.cancellation import CancellationToken

logger = logging.getLogger(__name__)

DEFAULT_MAX_SPAWN_PER_WORKFLOW = 50
DEFAULT_MAX_CONCURRENT_SPAWNS = 5


class DwVerificationMode(StrEnum):
    NONE = "none"
    ADVERSARIAL = "adversarial"


class WorkflowRunGuard:
    """Hard cap on total spawns, concurrent in-flight sub-agents, and merge result collection."""

    __slots__ = (
        "_max_concurrent",
        "_max_spawns",
        "_merge_results",
        "_semaphore",
        "_spawn_count",
    )

    def __init__(
        self,
        *,
        max_spawns: int = DEFAULT_MAX_SPAWN_PER_WORKFLOW,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT_SPAWNS,
    ) -> None:
        self._max_spawns = max_spawns
        self._max_concurrent = max_concurrent
        self._spawn_count = 0
        self._merge_results: list[dict[str, object]] = []
        self._semaphore = asyncio.Semaphore(max_concurrent)

    @property
    def spawn_count(self) -> int:
        return self._spawn_count

    @property
    def merge_results(self) -> list[dict[str, object]]:
        return list(self._merge_results)

    async def acquire_spawn_slot(self, *, readonly: bool = False) -> str | None:
        if self._spawn_count >= self._max_spawns:
            return f"Workflow spawn limit reached ({self._max_spawns}). Reduce parallel tasks or split the workflow."
        self._spawn_count += 1
        await self._semaphore.acquire()
        return None

    def release_spawn_slot(self, *, readonly: bool = False) -> None:
        self._semaphore.release()

    def record_merge_candidate(self, result: dict[str, object]) -> None:
        if not merge_candidate_from_spawn_dict(result):
            return
        task_id = result.get("task_id")
        if isinstance(task_id, str):
            for existing in self._merge_results:
                if existing.get("task_id") == task_id:
                    return
        self._merge_results.append(result)


def _normalize_spawn_result(result: object, *, task_id: str, agent_type: str) -> dict[str, object]:
    if isinstance(result, dict):
        return result

    status_val = getattr(result, "status", None)
    return {
        "success": getattr(result, "success", False),
        "task_id": getattr(result, "task_id", task_id),
        "agent_type": getattr(result, "agent_type", agent_type),
        "result": getattr(result, "result", None),
        "error": getattr(result, "error", None),
        "status": (
            status_val.value
            if status_val is not None and hasattr(status_val, "value")
            else str(status_val or "unknown")
        ),
    }


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
    verification_mode: Literal["none", "adversarial"] = Field(
        default="none",
        description='Verification: "none" (default) or "adversarial" (worker+verifier retry loop).',
    )
    verifier_agent_type: str | None = Field(
        default=None,
        description="Optional verifier agent type when verification_mode is adversarial.",
    )
    max_verification_rounds: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Max adversarial verification rounds (1-5).",
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
    event_queue: asyncio.Queue[dict[str, object]] | None = None
    message_id: str = ""
    run_guard: WorkflowRunGuard | None = None

    async def _emit_spawn_stage(
        self,
        message: str,
        *,
        level: str = "info",
        category: str = "subagent",
    ) -> None:
        if self.event_queue is None or not self.message_id:
            return
        event = build_workflow_stage_event(
            self.message_id,
            message,
            level=level,
            category=category,
        )
        await self.event_queue.put(event)

    def _run(
        self,
        task_id: str,
        agent_type: str,
        task_description: str,
        readonly: bool = False,
        verification_mode: Literal["none", "adversarial"] = "none",
        verifier_agent_type: str | None = None,
        max_verification_rounds: int = 2,
    ) -> object:
        raise NotImplementedError("SpawnSubagentTool only supports async execution.")

    async def _arun(
        self,
        task_id: str,
        agent_type: str = "generalPurpose",
        task_description: str = "",
        readonly: bool = False,
        verification_mode: Literal["none", "adversarial"] = "none",
        verifier_agent_type: str | None = None,
        max_verification_rounds: int = 2,
    ) -> object:
        if self.cancel_token and getattr(self.cancel_token, "is_cancelled", False):
            return {
                "success": False,
                "task_id": task_id,
                "agent_type": agent_type,
                "result": None,
                "error": "Workflow cancelled by user.",
            }

        cache_params = SpawnCacheParams(
            agent_type=agent_type,
            task_description=task_description,
            readonly=readonly,
            verification_mode=verification_mode,
            verifier_agent_type=verifier_agent_type,
            max_verification_rounds=max_verification_rounds,
        )

        if self.store:
            cached = self.store.get_cached_result(
                self.workflow_id,
                task_id,
                expected=cache_params,
            )
            if cached and cached.get("workspace_merge_status") == "pending":
                logger.info(
                    "DW cache miss (pending merge): workflow=%s task=%s",
                    self.workflow_id,
                    task_id,
                )
                cached = None
            if cached:
                logger.info("DW cache hit: workflow=%s task=%s", self.workflow_id, task_id)
                await self._emit_spawn_stage(f"Using cached result for sub-agent `{task_id}`.")
                if self.run_guard is not None and cached.get("workspace_merge_status") != "merged":
                    self.run_guard.record_merge_candidate(cached)
                return cached

        guard_error: str | None = None
        if self.run_guard is not None:
            guard_error = await self.run_guard.acquire_spawn_slot(readonly=readonly)
        if guard_error:
            await self._emit_spawn_stage(
                f"Sub-agent `{task_id}` blocked: {guard_error}",
                level="warn",
            )
            return {
                "success": False,
                "task_id": task_id,
                "agent_type": agent_type,
                "result": None,
                "error": guard_error,
            }

        from myrm_agent_harness.agent.sub_agents.types import (
            SubagentConfig,
            WorkspacePolicy,
        )

        config = None
        if self.catalog:
            config = await cast("SubagentCatalog", self.catalog).resolve(agent_type)
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

        config = apply_readonly_to_config(config, readonly)
        config = enforce_spawn_policy_on_config(config)

        # DW non-readonly spawns always use ISOLATED_COPY; batch_merge runs after PTC execution.
        parallel_batch = not readonly and self.run_guard is not None
        child_context = build_child_context_from_parent_agent(self.parent_agent)
        workspace_prep = apply_spawn_workspace_isolation(
            config=config,
            child_context=child_context,
            readonly=readonly,
            parallel_write_batch=parallel_batch,
        )
        config = workspace_prep.config
        child_context = workspace_prep.child_context

        use_adversarial = verification_mode == DwVerificationMode.ADVERSARIAL.value
        stage_label = (
            f"Spawning sub-agent `{task_id}` ({agent_type}) with adversarial verification..."
            if use_adversarial
            else f"Spawning sub-agent `{task_id}` ({agent_type})..."
        )
        await self._emit_spawn_stage(stage_label)

        try:
            try:
                with memory_isolation_scope(parent_agent=self.parent_agent, config=config):
                    if use_adversarial:
                        if not hasattr(self.parent_agent, "_subagent_manager"):
                            logger.warning(
                                "DW adversarial verify unavailable (no SubagentManager); falling back to direct spawn"
                            )
                            await self._emit_spawn_stage(
                                f"Sub-agent `{task_id}`: adversarial verify unavailable, using direct spawn.",
                                level="warn",
                            )
                            result = await cast("BaseAgent", self.parent_agent)._spawn_child(
                                task_id=task_id,
                                agent_type=agent_type,
                                task_description=task_description,
                                config=config,
                                context=child_context,
                                tool_registry_getter=cast(
                                    "Callable[[], list[BaseTool]]",
                                    self.tool_registry_getter,
                                ),
                                wait=True,
                                cancel_token=cast("CancellationToken | None", self.cancel_token),
                            )
                        else:
                            manager = self.parent_agent._subagent_manager
                            from myrm_agent_harness.agent.sub_agents.orchestrator import (
                                run_with_verification,
                            )

                            v_type = verifier_agent_type or agent_type
                            verifier_config = config
                            if self.catalog:
                                resolved_verifier = await cast("SubagentCatalog", self.catalog).resolve(v_type)
                                if resolved_verifier is not None:
                                    verifier_config = resolved_verifier
                            verifier_config = replace(
                                verifier_config,
                                workspace_policy=WorkspacePolicy.READ_ONLY_SANDBOX,
                            )

                            result = await run_with_verification(
                                manager=manager,
                                worker_type=agent_type,
                                worker_config=config,
                                worker_task=task_description,
                                verifier_type=v_type,
                                verifier_config=verifier_config,
                                context=child_context,
                                tool_registry_getter=cast(
                                    "Callable[[], list[BaseTool]]",
                                    self.tool_registry_getter,
                                ),
                                max_rounds=max_verification_rounds,
                                cancel_token=cast("CancellationToken | None", self.cancel_token),
                                task_id=task_id,
                            )
                    else:
                        result = await cast("BaseAgent", self.parent_agent)._spawn_child(
                            task_id=task_id,
                            agent_type=agent_type,
                            task_description=task_description,
                            config=config,
                            context=child_context,
                            tool_registry_getter=cast(
                                "Callable[[], list[BaseTool]]",
                                self.tool_registry_getter,
                            ),
                            wait=True,
                            cancel_token=cast("CancellationToken | None", self.cancel_token),
                        )
            except Exception as e:
                logger.error("DW spawn failed: task=%s error=%s", task_id, e)
                await self._emit_spawn_stage(
                    f"Sub-agent `{task_id}` failed: {type(e).__name__}: {e}",
                    level="warn",
                )
                return {
                    "success": False,
                    "task_id": task_id,
                    "agent_type": agent_type,
                    "result": None,
                    "error": f"{type(e).__name__}: {e}",
                }
        finally:
            if self.run_guard is not None:
                self.run_guard.release_spawn_slot(readonly=readonly)

        final_result = _normalize_spawn_result(result, task_id=task_id, agent_type=agent_type)

        if self.run_guard is not None:
            self.run_guard.record_merge_candidate(final_result)

        if self.store:
            self.store.save_result(
                workflow_id=self.workflow_id,
                task_id=task_id,
                agent_type=agent_type,
                task_description=task_description,
                result=sanitize_spawn_result_for_store(final_result),
                spawn_params=cache_params,
            )

        if final_result.get("success"):
            await self._emit_spawn_stage(f"Sub-agent `{task_id}` completed.")
        else:
            error_text = final_result.get("error") or "unknown error"
            await self._emit_spawn_stage(
                f"Sub-agent `{task_id}` failed: {error_text}",
                level="warn",
            )

        return final_result


# ---------------------------------------------------------------------------
# NotifyProgressTool — real-time workflow stage notifications from PTC scripts
# ---------------------------------------------------------------------------


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
        event = build_workflow_stage_event(
            self.message_id,
            message,
            progress=progress,
            step_index=step_index,
            total_steps=total_steps,
            category=category,
            level=level,
        )
        await self.event_queue.put(event)
        display_message = normalize_dw_message(message)
        return {"success": True, "message": display_message}


class HumanAskInput(BaseModel):
    """Input schema for myrm_tools.human_ask mid-run human-in-the-loop gate."""

    model_config = ConfigDict(extra="ignore")

    question: str = Field(
        ...,
        description="The question or decision prompt to present to the user.",
    )
    options: list[str] = Field(
        default_factory=list,
        description="Optional list of discrete options for multiple-choice decisions (e.g. ['continue', 'abort']).",
    )
    timeout_seconds: int = Field(
        default=300,
        description="Timeout in seconds to wait for user input (default 300s). Falls back to default_action on timeout.",
    )
    default_action: str = Field(
        default="",
        description="Fallback answer or action if user response times out.",
    )


class HumanAskTool(BaseTool):
    """PTC tool that suspends the Dynamic Workflow execution and requests mid-run user input via PhaseWaiter."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "human_ask"
    description: str = (
        "Ask the user a question or present a critical decision during Dynamic Workflow execution. "
        "Suspends workflow execution until the user responds or timeout elapses."
    )
    args_schema: type[BaseModel] = HumanAskInput

    event_queue: asyncio.Queue[dict[str, object]]
    message_id: str = ""
    ask_gate_callable: Callable[[str, list[str], int, str], Awaitable[str | None]] | None = None
    cancel_token: CancellationToken | None = None

    def _run(
        self,
        question: str,
        options: list[str] | None = None,
        timeout_seconds: int = 300,
        default_action: str = "",
    ) -> object:
        raise NotImplementedError("HumanAskTool only supports async execution.")

    async def _arun(
        self,
        question: str,
        options: list[str] | None = None,
        timeout_seconds: int = 300,
        default_action: str = "",
    ) -> dict[str, object]:
        if self.cancel_token and self.cancel_token.is_cancelled:
            return {
                "success": False,
                "answer": default_action or None,
                "error": "Workflow cancelled by user before human_ask",
                "timed_out": False,
            }

        opts = options or []
        timeout_sec = max(5, min(timeout_seconds, 1800))

        # 1. Emit human_gate status event to frontend SSE
        gate_event = {
            "type": "status",
            "messageId": self.message_id,
            "data": {
                "phase": "human_gate",
                "status": "waiting",
                "question": question,
                "options": opts,
                "timeout_seconds": timeout_sec,
                "default_action": default_action,
                "source": "dynamic_workflow",
            },
        }
        await self.event_queue.put(gate_event)

        # 2. Invoke server-provided approval gate (PhaseWaiter bridge)
        answer: str | None = None
        timed_out = False
        error_msg = ""

        try:
            if self.ask_gate_callable is not None:
                answer = await self.ask_gate_callable(question, opts, timeout_sec, default_action)
            else:
                # Direct fallback when gate callable is not injected (e.g. unattended tests)
                logger.info("HumanAskTool has no server ask_gate_callable; using default_action='%s'", default_action)
                answer = default_action or (opts[0] if opts else "continue")
        except asyncio.TimeoutError:
            timed_out = True
            answer = default_action
            error_msg = f"User response timed out after {timeout_sec}s; applied default: '{default_action}'"
            logger.warning("HumanAskTool timed out: message_id=%s, applied default='%s'", self.message_id, default_action)
        except Exception as exc:
            error_msg = f"human_ask failed: {exc}"
            logger.error("HumanAskTool error: %s", exc, exc_info=True)

        # 3. Emit resolved status event to frontend SSE
        resolved_event = {
            "type": "status",
            "messageId": self.message_id,
            "data": {
                "phase": "human_gate",
                "status": "resolved",
                "answer": answer,
                "timed_out": timed_out,
                "source": "dynamic_workflow",
            },
        }
        await self.event_queue.put(resolved_event)

        return {
            "success": True if error_msg == "" else False,
            "answer": answer,
            "error": error_msg,
            "timed_out": timed_out,
        }

