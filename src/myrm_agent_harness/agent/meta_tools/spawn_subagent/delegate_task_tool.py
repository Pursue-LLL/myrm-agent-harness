"""Delegate task meta-tool (dual-mode: bound custom agent + dynamic ephemeral).

[INPUT]
- _delegate_budget (POS: Budget admission, policy enforcement, result caching, dynamic description)
- agent.sub_agents.types::SubagentCatalog, ControlScope, DelegateRole
- agent.base_agent::BaseAgent (POS: Base agent with streaming, token tracking, and artifacts)
- langchain.tools::tool
- pydantic::BaseModel, Field

[OUTPUT]
- create_delegate_task_tool: Factory function for delegate_task tool
- create_batch_delegate_tasks_tool: Factory function for budget-aware batch delegate orchestration
- create_delegate_parallel_tasks_tool: Swarm Fission interrupt tool (yield-resume parallel Map-Reduce)
- update_delegate_task_description: Async description refresher for catalog-driven prompt injection

[POS]
Unified delegate_task tool. Supports two modes:
  Mode A (Bound Custom Agent): Pass agent_id to call a pre-configured custom agent.
  Mode B (Dynamic Ephemeral): Pass instructions + tools to create a one-off subagent.
Budget admission, policy denial, result caching, and dynamic description generation
are in _delegate_budget.py. This file contains the tool factories and execution logic.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import uuid4

from langchain.tools import tool
from pydantic import BaseModel, Field

from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
    _build_dynamic_description,
    _cache_key,
    _compute_payload_hash,
    _get_cached,
    _normalize_role,
    _policy_denied,
    _put_cache,
)
from myrm_agent_harness.agent.parallel.summary import (
    inject_capacity_signal as _inject_capacity_signal,
)
from myrm_agent_harness.agent.sub_agents.types import (
    ControlScope,
    DelegateRole,
    MemoryIsolationPolicy,
    SubagentCatalog,
    SubAgentResult,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.runtime.cancellation import get_cancel_token

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.agent.base_agent import BaseAgent

logger = get_agent_logger(__name__)


def create_delegate_task_tool(
    parent_agent: BaseAgent,
    tool_registry_getter: Callable[[], list[object]],
    catalog: SubagentCatalog,
    parent_type: str | None = None,
    allowed_types: list[str] | None = None,
) -> BaseTool:
    """Create delegate_task tool for the parent agent.

    Args:
        parent_agent: The parent agent instance that can spawn children.
        tool_registry_getter: Function that returns available tools for subagent.
        catalog: The catalog to resolve subagent configurations.
        parent_type: Parent agent type (for nesting check).
        allowed_types: Restrict which agent types can be spawned (L0 type admission).
            None = all catalog types are available.

    Returns:
        delegate_task tool function.
    """

    class SpawnSubagentInput(BaseModel):
        agent_type: str = Field(
            description="Type of subagent (must match an exact type_id from the <Available_Team_Roster> or context list)"
        )
        objective: str = Field(description="Clear description of the core objective for the subagent")
        context_files: list[str] = Field(
            default_factory=list,
            description="List of relevant file paths or resources for this task",
        )
        context: dict[str, object] | None = Field(default=None, description="Optional context data")
        wait: bool = Field(
            default=False,
            description="Wait for result (true) or return task_id (false)",
        )
        readonly: bool = Field(
            default=False,
            description="If true, subagent cannot write files or run bash commands",
        )
        complexity_tier: str | None = Field(
            default=None,
            description="Optional explicit complexity tier ('simple', 'standard', 'reasoning'). If set to 'simple', routes to a fast/cheap model (good for web scraping, basic bash). If 'reasoning', routes to a powerful reasoning model. If omitted, the system auto-detects based on the task.",
        )
        role: DelegateRole = Field(
            default=DelegateRole.LEAF,
            description="Delegation role for the child. 'leaf' cannot delegate further. 'orchestrator' may spawn child workers only when the catalog configuration explicitly allows it.",
        )
        verifier_prompt: str | None = Field(
            default=None,
            description="Optional. If provided, enables adversarial verification. The verifier will use this prompt to critique the result and force a retry if it fails.",
        )
        verifier_agent_type: str | None = Field(
            default=None,
            description="Optional. The agent type to use for the verifier. If omitted, defaults to the same agent type as the worker.",
        )
        max_verification_rounds: int = Field(
            default=2,
            description="Maximum number of retry rounds if the verifier rejects the output.",
        )

    @tool("delegate_task_tool", args_schema=SpawnSubagentInput)
    async def delegate_task_func(
        agent_type: str,
        objective: str,
        context_files: list[str] | None = None,
        context: dict[str, object] | None = None,
        wait: bool = False,
        readonly: bool = False,
        complexity_tier: str | None = None,
        role: DelegateRole = DelegateRole.LEAF,
        verifier_prompt: str | None = None,
        verifier_agent_type: str | None = None,
        max_verification_rounds: int = 2,
    ) -> dict[str, object]:
        """Spawn a specialized subagent to handle a specific task.

        CRITICAL:
        1. You MUST check the `<Available_Team_Roster>` (if provided in your messages) or know the available agent types before delegating.
        2. Parallel execution: spawn with wait=false; check results with list_subagents_tool.
        3. Synchronous execution: spawn with wait=true for immediate result.
        4. Do NOT delegate ultra-simple actions or sequential steps.
        5. If using wait=false, you MUST actively call list_subagents_tool later to get results!
        """
        if allowed_types is not None and agent_type not in allowed_types:
            return {
                "success": False,
                "error": f"Agent type '{agent_type}' not allowed.",
            }

        if verifier_prompt and not wait:
            return {
                "success": False,
                "error": "Adversarial verification requires wait=True. Please set wait=True or remove verifier_prompt.",
            }

        task = objective
        if context_files:
            task += "\n\nRelevant files/resources:\n" + "\n".join(f"- {f}" for f in context_files)

        if context:
            try:
                context_str = json.dumps(context, ensure_ascii=False, indent=2)
                task += f"\n\nAdditional Context Data:\n```json\n{context_str}\n```"
            except Exception as e:
                logger.warning("Failed to serialize context dict: %s", e)
                task += f"\n\nAdditional Context Data:\n{context!s}"

        parent_ctx = getattr(parent_agent, "_last_context", None) or {}
        requested_role = _normalize_role(role)

        payload_hash = _compute_payload_hash(agent_type, task, requested_role.value, context)
        history_hashes = list(parent_ctx.get("subagent_payload_hashes", []))
        if history_hashes.count(payload_hash) >= 1:
            logger.error(
                "Payload Deadlock Prevented! Agent '%s' is repeating the exact same task. Hash: %s",
                agent_type,
                payload_hash[:8],
            )
            return {
                "success": False,
                "error": f"Safety interception: Detected meaningless repeated delegation loop. You are attempting to call '{agent_type}' with identical parameters (fingerprint: {payload_hash[:8]}). Reflect on the failure reason from the last call, modify the instructions or provide new context before retrying.",
                "task_id": "deadlock-prevented",
            }

        history_hashes.append(payload_hash)
        parent_ctx["subagent_payload_hashes"] = history_hashes

        sid = str(parent_ctx.get("session_id", ""))
        key = _cache_key(agent_type, task, context, session_id=sid, role=requested_role.value)
        cached = _get_cached(key)
        if cached is not None:
            return {
                "success": True,
                "result": cached,
                "task_id": f"cached-{key}",
                "cached": True,
            }

        task_id = str(uuid4())[:8]

        config = await catalog.resolve(agent_type)
        if not config:
            return {
                "success": False,
                "error": f"Agent type '{agent_type}' not found in catalog.",
            }

        parent_manager = getattr(parent_agent, "_subagent_manager", None)
        current_depth = int(getattr(parent_manager, "current_depth", 0))
        allowed_type_set = frozenset(allowed_types) if allowed_types is not None else None

        if requested_role == DelegateRole.ORCHESTRATOR:
            if config.control_scope != ControlScope.ORCHESTRATOR:
                return _policy_denied(
                    reason="role_escalation_denied",
                    requested_role=requested_role,
                    effective_scope=config.control_scope,
                    agent_type=agent_type,
                    task_id=task_id,
                    session_id=sid,
                    details=(f"Agent type '{agent_type}' is not allowed to run as an orchestrator."),
                )
            if config.max_spawn_depth <= current_depth:
                return _policy_denied(
                    reason="max_spawn_depth_denied",
                    requested_role=requested_role,
                    effective_scope=config.control_scope,
                    agent_type=agent_type,
                    task_id=task_id,
                    session_id=sid,
                    details=(
                        f"Agent type '{agent_type}' cannot orchestrate at depth {current_depth}; "
                        f"max_spawn_depth={config.max_spawn_depth}."
                    ),
                )
            config = replace(
                config,
                delegation_role=DelegateRole.ORCHESTRATOR,
                delegation_catalog=catalog,
                delegation_allowed_types=allowed_type_set,
            )
        else:
            config = replace(
                config,
                control_scope=ControlScope.LEAF,
                delegation_role=DelegateRole.LEAF,
                delegation_catalog=None,
                delegation_allowed_types=None,
            )

        if readonly:
            readonly_blocked = frozenset(
                {
                    "write_file",
                    "execute_terminal_command",
                    "bash_run_command",
                    "git_commit",
                }
            )
            readonly_hint = "\n\n[READONLY MODE] You are in read-only mode. You can only read and analyze — do NOT attempt file writes, terminal commands, or git commits."
            config = replace(
                config,
                disallowed_tools=config.disallowed_tools | readonly_blocked,
                system_prompt=config.system_prompt + readonly_hint,
            )

        # Enforce LEAF control scope: subagents cannot spawn further subagents
        if config.control_scope == ControlScope.LEAF:
            config = replace(config, max_spawn_depth=0)

        # Enforce memory isolation: block memory write tools for READ_ONLY_GLOBAL
        if config.memory_isolation == MemoryIsolationPolicy.READ_ONLY_GLOBAL:
            memory_write_tools = frozenset({"memory_save_tool", "memory_manage_tool"})
            config = replace(config, disallowed_tools=config.disallowed_tools | memory_write_tools)

        cancel_token = get_cancel_token()

        child_context = dict(context or {})
        child_context["subagent_payload_hashes"] = history_hashes
        for _ctx_key in ("workspace_binding", "workspaces_storage_root", "user_id", "session_id"):
            if _ctx_key in parent_ctx:
                child_context[_ctx_key] = parent_ctx[_ctx_key]

        from myrm_agent_harness.agent.workspace_coordination.policy import (
            apply_parallel_write_isolation,
        )

        config, child_context = apply_parallel_write_isolation(
            config=config,
            child_context=child_context,
            readonly=readonly,
            parallel_write_batch=bool(getattr(parent_agent, "_parallel_write_batch_active", False)),
        )

        logger.info(
            "Spawning subagent: type=%s, task_id=%s, wait=%s, scope=%s",
            agent_type,
            task_id,
            wait,
            config.control_scope,
        )

        reset_token = None
        try:
            from myrm_agent_harness.agent._skill_agent_context import (
                _memory_manager_var,
                get_memory_manager,
            )
            from myrm_agent_harness.toolkits.memory.ephemeral import (
                EphemeralMemoryManager,
                ReadOnlyMemoryView,
            )

            global_mem = get_memory_manager()
            if global_mem:
                if config.memory_isolation == MemoryIsolationPolicy.COLLABORATIVE_SESSION:
                    if not hasattr(parent_agent, "_collaborative_memory"):
                        parent_agent._collaborative_memory = EphemeralMemoryManager(global_mem)
                    reset_token = _memory_manager_var.set(parent_agent._collaborative_memory)
                elif config.memory_isolation == MemoryIsolationPolicy.READ_ONLY_GLOBAL:
                    reset_token = _memory_manager_var.set(ReadOnlyMemoryView(global_mem))
                else:
                    ephemeral_mem = EphemeralMemoryManager(global_mem)
                    reset_token = _memory_manager_var.set(ephemeral_mem)

            if verifier_prompt and wait:
                logger.info(f"Running adversarial verification for subagent {task_id}")
                from myrm_agent_harness.agent.sub_agents.orchestrator import run_with_verification
                from myrm_agent_harness.agent.sub_agents.types import WorkspacePolicy

                v_type = verifier_agent_type or agent_type
                v_config = await catalog.resolve(v_type)
                if not v_config:
                    logger.warning(
                        "Verifier agent type '%s' not found, falling back to worker type '%s'", v_type, agent_type
                    )
                    v_type = agent_type
                    v_config = config

                verifier_config = replace(v_config, workspace_policy=WorkspacePolicy.READ_ONLY_SANDBOX)

                result = await run_with_verification(
                    manager=parent_manager,
                    worker_type=agent_type,
                    worker_config=config,
                    worker_task=task,
                    verifier_type=v_type,
                    verifier_config=verifier_config,
                    context=child_context,
                    tool_registry_getter=tool_registry_getter,
                    max_rounds=max_verification_rounds,
                    verifier_task_template=verifier_prompt,
                )
            else:
                result = await parent_agent._spawn_child(
                    task_id=task_id,
                    agent_type=agent_type,
                    task_description=task,
                    config=config,
                    context=child_context,
                    tool_registry_getter=tool_registry_getter,
                    wait=wait,
                    parent_type=parent_type,
                    cancel_token=cancel_token,
                    complexity_tier=complexity_tier,
                )

            if isinstance(result, SubAgentResult):
                from myrm_agent_harness.agent.sub_agents.types import SubAgentStatus

                while result.status == SubAgentStatus.PENDING_APPROVAL:
                    # 1. Subagent suspended via GraphInterrupt. Prepare payload for Parent's interrupt.
                    interrupt_payload: dict[str, object] = {
                        "action_type": "subagent_approval",
                        "subagent_task_id": task_id,
                    }
                    if result.payload and isinstance(result.payload, dict):
                        interrupt_payload.update(result.payload)

                        # Adapt payload for frontend PolymorphicApprovalCard
                        # Frontend expects `tool_calls` array with {name, args}
                        action_requests = result.payload.get("actionRequests", [])
                        tool_calls: list[dict[str, object]] = []
                        if not isinstance(action_requests, list):
                            action_requests = []
                        for req in action_requests:
                            if isinstance(req, dict):
                                raw_args = req.get("args", {})
                                args: dict[str, object] = dict(raw_args) if isinstance(raw_args, dict) else {}
                                command_spans = req.get("command_spans")
                                if command_spans:
                                    args["command_spans"] = command_spans
                                command_span_risks = req.get("command_span_risks")
                                if command_span_risks:
                                    args["command_span_risks"] = command_span_risks
                                command_span_reasons = req.get("command_span_reasons")
                                if command_span_reasons:
                                    args["command_span_reasons"] = command_span_reasons
                                tool_calls.append(
                                    {
                                        "name": req.get("action", "unknown"),
                                        "args": args,
                                    }
                                )
                        if tool_calls:
                            interrupt_payload["tool_calls"] = tool_calls

                    else:
                        interrupt_payload["payload"] = result.payload

                    # Suspend parent graph (releases concurrency, avoids 300s timeout)
                    from langgraph.types import Command, interrupt

                    decisions = interrupt(interrupt_payload)
                    logger.info("Resuming subagent %s after UI approval", task_id)
                    result = await parent_agent._spawn_child(
                        task_id=task_id,
                        agent_type=agent_type,
                        task_description=task,
                        config=config,
                        context=child_context,
                        tool_registry_getter=tool_registry_getter,
                        wait=wait,
                        parent_type=parent_type,
                        cancel_token=cancel_token,
                        resume_command=Command(resume=decisions),
                        complexity_tier=complexity_tier,
                    )

            if isinstance(result, SubAgentResult):
                result_dict = result.to_dict()
                if wait:
                    if result_dict.get("success"):
                        _put_cache(key, result_dict.get("result", {}))
                    return _inject_capacity_signal(result_dict, parent_agent)

            if isinstance(result, dict) and wait and result.get("success"):
                _put_cache(key, result.get("result", {}))

            final_result = result if isinstance(result, dict) else {"success": False, "error": str(result)}
            return _inject_capacity_signal(final_result, parent_agent)

        except TimeoutError:
            logger.error("Subagent %s timed out after %ds", task_id, config.timeout_seconds)
            return {
                "success": False,
                "error": f"Timeout after {config.timeout_seconds}s",
                "task_id": task_id,
            }
        except Exception as e:
            from myrm_agent_harness.toolkits.llms.errors.classifier import (
                ErrorKind,
                classify_error,
            )

            error_kind = classify_error(e)
            if error_kind == ErrorKind.FORMAT_ERROR:
                logger.warning("Subagent %s failed due to FORMAT_ERROR: %s", task_id, e)
                return {
                    "success": False,
                    "error": f"Subagent execution failed due to LLM output format validation error ({e}). Please provide simpler structured instructions and retry.",
                    "task_id": task_id,
                }

            logger.error("Failed to spawn subagent %s: %s", task_id, e, exc_info=True)
            return {
                "success": False,
                "error": f"{type(e).__name__}: {e}",
                "task_id": task_id,
            }
        finally:
            if reset_token:
                try:
                    from myrm_agent_harness.agent._skill_agent_context import _memory_manager_var

                    _memory_manager_var.reset(reset_token)
                except Exception as e:
                    logger.warning("Failed to reset memory manager context var: %s", e)

    return delegate_task_func


async def update_delegate_task_description(
    delegate_tool: BaseTool,
    catalog: SubagentCatalog,
    allowed_types: list[str] | None = None,
) -> None:
    """Update delegate_task tool description with available agent types from catalog.

    Call this in an async context after creating the tool to inject
    dynamic agent type information into the tool description.
    """
    dynamic_desc = await _build_dynamic_description(catalog, allowed_types)
    delegate_tool.description = dynamic_desc


from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (  # noqa: E402
    BatchDelegateInput,
    TaskRequest,
    create_batch_delegate_tasks_tool,
    create_delegate_parallel_tasks_tool,
)

__all__ = [
    "BatchDelegateInput",
    "TaskRequest",
    "create_batch_delegate_tasks_tool",
    "create_delegate_parallel_tasks_tool",
    "create_delegate_task_tool",
    "update_delegate_task_description",
]
