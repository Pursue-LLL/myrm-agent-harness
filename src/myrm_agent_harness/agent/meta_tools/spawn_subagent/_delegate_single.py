"""Single-mode execution for delegate_task: admission, spawn, verification and approval resume.

[INPUT]
- _delegate_budget::_compute_payload_hash, _normalize_role, _policy_denied (POS: repeat fingerprint, role normalization, policy denial)
- delegation_pause_gate::is_delegation_paused (POS: Session delegation pause check)
- agent.sub_agents.approval_journal::ApprovalJournal, delegation_task_id (POS: replay-safe id and approval round-trips of one delegation)
- agent.sub_agents.spawn_capability::derive_spawn_capability (POS: per-spawn OCap handle minted from the parent's authoritative scope)
- agent.sub_agents.spawn_prep (POS: spawn preparation SSOT shared with Dynamic Workflow: readonly floor, spawn policy, child context)
- agent.sub_agents.verifier_selection::resolve_verifier (POS: read-only verifier choice shared with Dynamic Workflow; refuses a verifier that cannot run commands)
- agent.sub_agents.orchestrator::run_with_verification (POS: worker + adversarial verifier loop)
- core.security.ocap::capability_scope (POS: binds the minted handle to the child run for the spawn's whole lifetime)
- agent.parallel.summary::inject_capacity_signal (POS: Capacity signal injection for context management)

[OUTPUT]
- execute_single_delegation: Run one delegation to a single subagent, optionally under adversarial verification

[POS]
Single-mode executor behind delegate_task_tool. Admits the requested agent type against the allowed types and the
catalog, refuses an identical repeated delegation, applies the role/readonly/spawn policy, binds the child's
capability handle, then spawns the worker (directly, or inside the verification loop) and carries it through the
UI approvals it raises. LangGraph re-executes this whole call after each approval, so the delegation id and the
approval steps come from the manager's approval journal rather than from this call's local state.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from functools import partial
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
    _compute_payload_hash,
    _normalize_role,
    _policy_denied,
)
from myrm_agent_harness.agent.parallel.summary import (
    inject_capacity_signal as _inject_capacity_signal,
)
from myrm_agent_harness.agent.sub_agents.approval_journal import ApprovalJournal, delegation_task_id
from myrm_agent_harness.agent.sub_agents.types import (
    ControlScope,
    DelegateRole,
    SubagentCatalog,
    SubAgentResult,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.runtime.cancellation import get_cancel_token

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.agent.base_agent import BaseAgent

logger = get_agent_logger(__name__)

# Per-request shell-span details the approval UI shows next to a pending command.
_COMMAND_SPAN_KEYS = ("command_spans", "command_span_risks", "command_span_reasons")


def _approval_interrupt_payload(task_id: str, result: SubAgentResult) -> dict[str, object]:
    """Build the interrupt payload that asks the UI to approve the tool calls a subagent is paused on."""
    payload: dict[str, object] = {"action_type": "subagent_approval", "subagent_task_id": task_id}
    if not (result.payload and isinstance(result.payload, dict)):
        payload["payload"] = result.payload
        return payload

    payload.update(result.payload)
    action_requests = result.payload.get("actionRequests", [])
    tool_calls: list[dict[str, object]] = []
    for request in action_requests if isinstance(action_requests, list) else []:
        if not isinstance(request, dict):
            continue
        raw_args = request.get("args", {})
        args: dict[str, object] = dict(raw_args) if isinstance(raw_args, dict) else {}
        for key in _COMMAND_SPAN_KEYS:
            if request.get(key):
                args[key] = request[key]
        tool_calls.append({"name": request.get("action", "unknown"), "args": args})
    if tool_calls:
        payload["tool_calls"] = tool_calls
    return payload


def _compose_task(objective: str, context_files: list[str] | None, context: dict[str, object] | None) -> str:
    """Append the file list and the structured context to the objective as the subagent's task text."""
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
    return task


async def execute_single_delegation(
    *,
    parent_agent: BaseAgent,
    tool_registry_getter: Callable[[], list[BaseTool]],
    catalog: SubagentCatalog,
    parent_type: str | None,
    allowed_types: list[str] | None,
    agent_type: str | None,
    objective: str | None,
    context_files: list[str] | None,
    context: dict[str, object] | None,
    wait: bool | None,
    readonly: bool,
    complexity_tier: str | None,
    role: DelegateRole,
    verifier_prompt: str | None,
    verifier_agent_type: str | None,
    max_verification_rounds: int,
) -> dict[str, object]:
    """Run one delegation to a single subagent, optionally under adversarial verification."""
    from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegation_pause_gate import (
        is_delegation_paused,
    )
    from myrm_agent_harness.agent.sub_agents.spawn_prep import coerce_spawn_readonly

    parent_ctx = getattr(parent_agent, "_last_context", None) or {}
    sid = str(parent_ctx.get("session_id", ""))
    parent_manager = getattr(parent_agent, "_subagent_manager", None)
    # A manager without a journal cannot replay: the delegation then runs once, exactly as a single execution does.
    journal = getattr(parent_manager, "approval_journal", None)
    approval_journal = journal if isinstance(journal, ApprovalJournal) else ApprovalJournal()

    if is_delegation_paused(sid):
        return {
            "success": False,
            "error": "Delegation is paused for this session. Resume delegation from the subagent dashboard before spawning new workers.",
            "session_id": sid,
        }

    if not agent_type or not objective:
        return {
            "success": False,
            "error": "agent_type and objective are required for mode=single.",
        }

    single_wait = wait if wait is not None else False

    if allowed_types is not None and agent_type not in allowed_types:
        return {
            "success": False,
            "error": f"Agent type '{agent_type}' not allowed.",
        }

    if verifier_prompt and not single_wait:
        return {
            "success": False,
            "error": "Adversarial verification requires wait=True. Please set wait=True or remove verifier_prompt.",
        }

    task = _compose_task(objective, context_files, context)

    requested_role = _normalize_role(role)
    effective_readonly = coerce_spawn_readonly(parent_agent, readonly)

    payload_hash = _compute_payload_hash(
        agent_type,
        task,
        requested_role.value,
        context,
        effective_readonly=effective_readonly,
        complexity_tier=complexity_tier,
        verifier_prompt=verifier_prompt,
        verifier_agent_type=verifier_agent_type,
        max_verification_rounds=max_verification_rounds,
    )
    task_id = delegation_task_id(payload_hash)
    history_hashes = list(parent_ctx.get("subagent_payload_hashes", []))
    # After a UI approval LangGraph re-executes this call: the fingerprint it registered the first time is its own.
    if payload_hash in history_hashes and not approval_journal.is_replay(task_id):
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

    if payload_hash not in history_hashes:
        history_hashes.append(payload_hash)
    parent_ctx["subagent_payload_hashes"] = history_hashes

    config = await catalog.resolve(agent_type)
    if not config:
        return {
            "success": False,
            "error": f"Agent type '{agent_type}' not found in catalog.",
        }
    verifier_fallback = config

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

    from myrm_agent_harness.agent.sub_agents.spawn_capability import derive_spawn_capability
    from myrm_agent_harness.agent.sub_agents.spawn_prep import (
        apply_readonly_to_config,
        apply_spawn_workspace_isolation,
        build_spawn_child_context,
        enforce_spawn_policy_on_config,
        memory_isolation_scope,
        resolve_delegate_parallel_write_batch,
    )
    from myrm_agent_harness.core.security.ocap import AttenuationError, capability_scope

    config = apply_readonly_to_config(config, effective_readonly)
    config = enforce_spawn_policy_on_config(config)

    cancel_token = get_cancel_token()

    child_context = build_spawn_child_context(parent_ctx=parent_ctx, payload_hashes=history_hashes)
    workspace_prep = apply_spawn_workspace_isolation(
        config=config,
        child_context=child_context,
        readonly=effective_readonly,
        parallel_write_batch=resolve_delegate_parallel_write_batch(parent_agent),
    )
    config = workspace_prep.config
    child_context = workspace_prep.child_context

    try:
        spawn_capability = derive_spawn_capability(
            parent_agent=parent_agent,
            agent_type=agent_type,
            readonly=effective_readonly,
            context_files=context_files,
        )
    except AttenuationError as exc:
        return {
            "success": False,
            "error": f"Subagent capability denied: {exc}",
            "task_id": task_id,
        }

    logger.info(
        "Spawning subagent: type=%s, task_id=%s, wait=%s, scope=%s",
        agent_type,
        task_id,
        single_wait,
        config.control_scope,
    )

    result: SubAgentResult | dict[str, object]
    try:
        from langgraph.types import Command, interrupt

        # The first spawn and the resume after a UI approval take identical arguments, so they cannot drift apart.
        spawn = partial(
            parent_agent._spawn_child,
            task_id=task_id,
            agent_type=agent_type,
            task_description=task,
            config=config,
            context=child_context,
            tool_registry_getter=tool_registry_getter,
            wait=single_wait,
            parent_type=parent_type,
            cancel_token=cancel_token,
            complexity_tier=complexity_tier,
        )
        approvals = approval_journal.scope(
            task_id,
            resume=lambda decisions: spawn(resume_command=Command(resume=decisions)),
            ask=lambda pending: interrupt(_approval_interrupt_payload(task_id, pending)),
        )
        with (
            memory_isolation_scope(parent_agent=parent_agent, config=config),
            capability_scope(spawn_capability),
        ):
            if verifier_prompt and single_wait:
                if parent_manager is None:
                    return {"success": False, "error": "Parent agent has no subagent manager.", "task_id": task_id}
                logger.info("Running adversarial verification for subagent %s", task_id)
                from myrm_agent_harness.agent.sub_agents.orchestrator import run_with_verification
                from myrm_agent_harness.agent.sub_agents.verifier_selection import (
                    VerifierUnavailableError,
                    resolve_verifier,
                )

                try:
                    v_type, verifier_config = await resolve_verifier(
                        catalog, verifier_agent_type, agent_type, verifier_fallback, tool_registry_getter()
                    )
                except VerifierUnavailableError as exc:
                    return {"success": False, "error": str(exc), "task_id": task_id}

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
                    cancel_token=cancel_token,
                    task_id=task_id,
                    approval_scope=approvals,
                )
            else:
                result = await approvals.settle(spawn)

            if isinstance(result, SubAgentResult) and single_wait:
                return _inject_capacity_signal(result.to_dict(), parent_agent)

            final_result = result if isinstance(result, dict) else {"success": False, "error": str(result)}
            return _inject_capacity_signal(final_result, parent_agent)

    except TimeoutError:
        timeout_msg = f"after {config.timeout_seconds}s" if config.timeout_seconds is not None else ""
        logger.error("Subagent %s timed out %s", task_id, timeout_msg)
        return {
            "success": False,
            "error": f"Timeout {timeout_msg}".strip(),
            "task_id": task_id,
        }
    except Exception as e:
        from langgraph.errors import GraphInterrupt

        if isinstance(e, GraphInterrupt):
            raise

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
