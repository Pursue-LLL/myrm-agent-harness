"""Batch Processor for Agent Security Approvals.

Handles the batch processing of tool calls, including security evaluation,
allowlist checking, and generation of approval requests.

[INPUT]
- agent.security.approval_flow::DEFAULT_USER_ID, get_allowlist (POS: Core component for "Always Allow" feature in Human-in-the-Loop approval system.)
- agent.security.guards.skill_approval_hook::HookAction, SkillApprovalHook, SkillHookVerdict (POS: Integrated into tool_interceptor_middleware between the onion policy engine (L1-L3) and HITL approval. When a skill returns require_approval, the request is forwarded to the existing HITL approval flow.)
- agent.security.types::PermissionAction, RecentToolCall, ReviewResult, SecurityConfig (POS: Foundation layer of the security type hierarchy. All other security modules import from here; this module imports from none of them.)

[OUTPUT]
- register_security_reviewer: Register or unregister a Transcript Classifier for auto-mode.
- reset_runtime_domains: Reset runtime-approved domains (call at session start).
- evaluate_tool_batch: Evaluate all tool calls and classify them into approved/denied/pending.
- build_interrupt_payload: Build LangChain-standard interrupt payload for batch approval.
- apply_approval_decisions: Apply user decisions to tool_calls and generate ToolMessages.

[POS]
Batch Processor for Agent Security Approvals.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

from langchain_core.messages import ToolCall

from myrm_agent_harness.agent.security.approval_flow import (
    DEFAULT_USER_ID,
    get_allowlist,
)
from myrm_agent_harness.agent.security.audit import record_decision
from myrm_agent_harness.agent.security.engine import (
    evaluate_tool_call,
    extract_url_domains,
)
from myrm_agent_harness.agent.security.guards.skill_approval_hook import (
    HookAction,
)
from myrm_agent_harness.agent.security.tool_registry import resolve_permission_type
from myrm_agent_harness.agent.security.types import (
    PermissionAction,
    RecentToolCall,
    SecurityConfig,
)

from . import _batch_review
from ._batch_decisions import apply_approval_decisions, build_interrupt_payload
from ._batch_review import (
    _evaluate_skill_hooks_for_tool,
    _get_runtime_domains,
    _run_llm_review,
    _truncate_tool_args,
    register_security_reviewer,
    reset_runtime_domains,
)
from .helpers import ThresholdBreach, is_threshold_breached, record_approval, record_denial

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Re-export for backward compatibility
__all__ = [
    "apply_approval_decisions",
    "build_interrupt_payload",
    "evaluate_tool_batch",
    "register_security_reviewer",
    "reset_runtime_domains",
]


async def evaluate_tool_batch(
    tool_calls: list[ToolCall],
    config: SecurityConfig,
    is_cron: bool,
    workspace_root: str | None,
    session_key: str,
    args_hashes: dict[int, str | None],
    intent_context: str | None = None,
    recent_tool_calls: tuple[RecentToolCall, ...] = (),
    taint_labels: frozenset[str] | None = None,
) -> tuple[
    list[tuple[int, ToolCall]],
    list[tuple[int, ToolCall, str]],
    list[tuple[int, ToolCall, str, str, dict[str, Any] | None]],
]:
    """Evaluate all tool calls and classify them into approved/denied/pending.

    Returns: (auto_approved, auto_denied, pending_approval)
    """
    auto_approved: list[tuple[int, ToolCall]] = []
    auto_denied: list[tuple[int, ToolCall, str]] = []
    pending_approval: list[tuple[int, ToolCall, str, str, dict[str, Any] | None]] = []

    if config.yolo_mode_enabled:
        yolo_active = True
        if config.yolo_mode_timeout and config.yolo_mode_enabled_at:
            elapsed = time.time() - config.yolo_mode_enabled_at
            if elapsed > config.yolo_mode_timeout:
                logger.warning(
                    "[YOLO] YOLO mode expired after %ds (session: %s)",
                    config.yolo_mode_timeout,
                    session_key,
                )
                yolo_active = False

        if yolo_active:
            suffix = "" if not config.yolo_mode_timeout else f" (expires in {config.yolo_mode_timeout}s)"
            logger.info(
                "[YOLO] Auto-approving all %d tool calls%s (session: %s)",
                len(tool_calls),
                suffix,
                session_key,
            )
            for idx, tool_call in enumerate(tool_calls):
                tool_name = tool_call.get("name", "unknown")
                record_decision(tool_name, "YOLO_AUTO_APPROVE", "YOLO mode enabled")
                auto_approved.append((idx, tool_call))
            return auto_approved, auto_denied, pending_approval

    for idx, tool_call in enumerate(tool_calls):
        tool_name = tool_call.get("name", "unknown")
        tool_input: dict[str, object] = tool_call.get("args", {})

        permission_type = resolve_permission_type(tool_name, tool_input)
        action, reason = evaluate_tool_call(permission_type, tool_input, config, workspace_root=workspace_root)

        extra_ctx = None
        if tool_name == "bash_code_execute_tool":
            from myrm_agent_harness.agent.security.checks import check_path_policy
            from myrm_agent_harness.agent.security.ptc_verifier import (
                extract_ptc_intent,
            )
            from myrm_agent_harness.agent.security.tool_registry import (
                get_ptc_safety_metadata,
            )

            command = str(tool_input.get("command", ""))
            ptc_intent = extract_ptc_intent(command)

            if ptc_intent:
                skill_name, ptc_tool_name, arguments = ptc_intent
                ptc_tool_name_full = f"ptc:{skill_name}.{ptc_tool_name}"
                extra_ctx = {"ptc_tool_name_full": ptc_tool_name_full}

                ptc_meta = get_ptc_safety_metadata(skill_name, ptc_tool_name)
                ptc_safety = None
                if ptc_meta:
                    ptc_safety, ptc_annotations = ptc_meta
                    extra_ctx["ptc_annotations"] = ptc_annotations

                # Path Policy Enforcement for PTC
                ptc_path = str(arguments.get("path", ""))
                if ptc_path and workspace_root:
                    path_action, path_reason = check_path_policy(ptc_path, config.path_policy, workspace_root)
                    if path_action == PermissionAction.DENY:
                        action = PermissionAction.DENY
                        reason = f"PTC {path_reason}"
                    elif path_action == PermissionAction.ASK and action != PermissionAction.DENY:
                        action = PermissionAction.ASK
                        reason = f"PTC {path_reason}"

                # Fast-Path Auto-Approve Logic
                if (
                    action == PermissionAction.ASK
                    and ptc_safety
                    and ptc_safety.is_read_only
                    and not ptc_safety.is_open_world
                ):
                    action = PermissionAction.ALLOW
                    reason = f"Fast-Path Auto-Approve for read-only MCP tool: {ptc_tool_name_full}"

        # Allowlist check: if still ASK, check if the tool is in user's allowlist
        if action == PermissionAction.ASK:
            from myrm_agent_harness.agent.middlewares._session_context import (
                get_approval_user_id,
            )

            allowlist = get_allowlist()
            user_id = get_approval_user_id() or DEFAULT_USER_ID
            await allowlist.load_user(user_id)
            effective_tool_name = extra_ctx.get("ptc_tool_name_full", tool_name) if extra_ctx else tool_name
            args_hash = args_hashes.get(idx)
            if allowlist.check(user_id, permission_type, effective_tool_name, args_hash):
                action = PermissionAction.ALLOW
                reason = f"Allowlist auto-approve: {effective_tool_name}"
                record_decision(tool_name, "ALLOWLIST_AUTO_APPROVE", reason)

        if action == PermissionAction.ALLOW:
            from myrm_agent_harness.agent.security.guards.taint_tracker import (
                get_taint_tracker,
            )

            taint_conflict = get_taint_tracker().check_sink(tool_name)
            if taint_conflict:
                # taint_conflict is a dict mapping TaintLabel to a set of sources
                conflict_labels = list(taint_conflict.keys())
                conflict_str = ", ".join(conflict_labels)

                # Format labels with sources for the LLM reviewer
                formatted_labels = set()
                for label, sources in taint_conflict.items():
                    if sources:
                        # Defensive truncation to prevent prompt explosion from too many sources
                        sources_list = list(sources)
                        if len(sources_list) > 5:
                            truncated_sources = sources_list[:5]
                            sources_str = (
                                ", ".join(truncated_sources) + f" ... and {len(sources_list) - 5} more sources"
                            )
                        else:
                            sources_str = ", ".join(sources_list)
                        formatted_labels.add(f"{label} (Sources: {sources_str})")
                    else:
                        formatted_labels.add(label)

                logger.warning(
                    "[TAINT] Escalating %s from ALLOW to ASK: session contains %s data",
                    tool_name,
                    conflict_str,
                )
                record_decision(
                    tool_name,
                    "TAINT_ESCALATE",
                    f"session contains {conflict_str} data",
                    tainted=True,
                )
                action = PermissionAction.ASK
                reason = f"Taint policy: session contains {conflict_str} data"

                # Smart Intent Guard: Try LLM review for taint conflict if enabled
                if (
                    config.auto_mode_enabled
                    and _batch_review._security_reviewer is not None
                    and is_threshold_breached() == ThresholdBreach.NONE
                ):
                    safe_tool_input = _truncate_tool_args(tool_input)
                    command_repr = f"Tool: {tool_name}\nArgs: {json.dumps(safe_tool_input)}"
                    review_result = await _run_llm_review(
                        command_repr,
                        workspace_root,
                        intent_context=intent_context,
                        taint_labels=frozenset(formatted_labels),
                        recent_tool_calls=recent_tool_calls,
                        model_id=config.auto_review_model,
                        trusted_domains=config.network_allowlist,
                    )
                    if review_result is not None:
                        from myrm_agent_harness.agent.security.types import (
                            ReviewDecision,
                        )

                        if review_result.decision == ReviewDecision.ALLOW:
                            logger.info(
                                "[LLM_REVIEW] Auto-allowed tainted %s: %s",
                                tool_name,
                                review_result.reason,
                            )
                            record_decision(tool_name, "LLM_REVIEW_ALLOW", review_result.reason)
                            auto_approved.append((idx, tool_call))
                            record_approval()
                            continue
                        if review_result.decision == ReviewDecision.DENY:
                            logger.warning(
                                "[LLM_REVIEW] Denied tainted %s: %s",
                                tool_name,
                                review_result.reason,
                            )
                            record_decision(tool_name, "LLM_REVIEW_DENY", review_result.reason)
                            hint = record_denial(tool_name)
                            auto_denied.append(
                                (
                                    idx,
                                    tool_call,
                                    f"Denied by security review (Taint): {review_result.reason}{hint}",
                                )
                            )
                            continue
                        if review_result.decision == ReviewDecision.UNCERTAIN:
                            logger.info(
                                "[LLM_REVIEW] Uncertain about tainted %s: %s",
                                tool_name,
                                review_result.reason,
                            )
                            # Inject the LLM's uncertainty reason into the HITL prompt so the user knows *why* it was flagged
                            reason = f"{reason}\n\n AI Security Reviewer Note:\n{review_result.reason}"
                            # Fall through to the default ASK behavior below
            else:
                # Auto Mode outbound check: delegate_agent actions that pass
                # the deterministic engine as ALLOW still need Classifier review
                # to prevent prompt-injection → malicious-delegation attacks.
                if (
                    permission_type == "delegate_agent"
                    and config.auto_mode_enabled
                    and _batch_review._security_reviewer is not None
                    and is_threshold_breached() == ThresholdBreach.NONE
                ):
                    safe_tool_input = _truncate_tool_args(tool_input)
                    command_repr = (
                        f"Tool: {tool_name}\nArgs: {json.dumps(safe_tool_input, ensure_ascii=False, default=str)}"
                    )
                    review_result = await _run_llm_review(
                        command_repr,
                        workspace_root,
                        intent_context=intent_context,
                        recent_tool_calls=recent_tool_calls,
                        model_id=config.auto_review_model,
                        trusted_domains=config.network_allowlist,
                    )
                    if review_result is not None:
                        from myrm_agent_harness.agent.security.types import ReviewDecision

                        if review_result.decision == ReviewDecision.DENY:
                            logger.warning(
                                "[OUTBOUND_CHECK] Denied delegation %s: %s",
                                tool_name,
                                review_result.reason,
                            )
                            record_decision(tool_name, "OUTBOUND_DENY", review_result.reason)
                            hint = record_denial(tool_name)
                            auto_denied.append(
                                (
                                    idx,
                                    tool_call,
                                    f"Delegation denied by outbound security check: {review_result.reason}{hint}",
                                )
                            )
                            continue
                        if review_result.decision == ReviewDecision.UNCERTAIN:
                            logger.info(
                                "[OUTBOUND_CHECK] Uncertain about delegation %s: %s",
                                tool_name,
                                review_result.reason,
                            )
                            record_decision(tool_name, "OUTBOUND_UNCERTAIN", review_result.reason)
                            pending_approval.append(
                                (
                                    idx,
                                    tool_call,
                                    permission_type,
                                    f"Delegation needs review: {review_result.reason}",
                                    extra_ctx,
                                )
                            )
                            continue
                        record_decision(tool_name, "OUTBOUND_ALLOW", "delegation cleared by outbound check")

                # Auto Mode shell escalation: shell_exec/code_interpreter actions
                # that pass the deterministic engine as ALLOW still need Classifier
                # review when the command is not trivially safe (Risk Classifier UNKNOWN).
                # Prevents user-defined broad ALLOW rules from bypassing Classifier.
                if (
                    permission_type in ("shell_exec", "code_interpreter")
                    and config.auto_mode_enabled
                    and _batch_review._security_reviewer is not None
                    and is_threshold_breached() == ThresholdBreach.NONE
                ):
                    from myrm_agent_harness.toolkits.code_execution.security.risk_classifier import (
                        CommandRiskLevel,
                        classify_command_risk,
                    )

                    shell_cmd = str(tool_input.get("command", "") or tool_input.get("code", "")).strip()
                    if shell_cmd and classify_command_risk(shell_cmd) != CommandRiskLevel.SAFE:
                        if extra_ctx and "ptc_annotations" in extra_ctx:
                            shell_cmd = f"{shell_cmd}\n\n# PTC Annotations: {extra_ctx['ptc_annotations']}"
                        review_result = await _run_llm_review(
                            shell_cmd,
                            workspace_root,
                            intent_context=intent_context,
                            recent_tool_calls=recent_tool_calls,
                            model_id=config.auto_review_model,
                            trusted_domains=config.network_allowlist,
                        )
                        if review_result is not None:
                            from myrm_agent_harness.agent.security.types import ReviewDecision

                            if review_result.decision == ReviewDecision.DENY:
                                logger.warning(
                                    "[SHELL_ESCALATION] Denied %s (ALLOW→DENY): %s",
                                    tool_name,
                                    review_result.reason,
                                )
                                record_decision(tool_name, "SHELL_ESCALATION_DENY", review_result.reason)
                                hint = record_denial(tool_name)
                                auto_denied.append(
                                    (
                                        idx,
                                        tool_call,
                                        f"Denied by auto-mode shell escalation: {review_result.reason}{hint}",
                                    )
                                )
                                continue
                            if review_result.decision == ReviewDecision.UNCERTAIN:
                                logger.info(
                                    "[SHELL_ESCALATION] Uncertain about %s: %s",
                                    tool_name,
                                    review_result.reason,
                                )
                                record_decision(tool_name, "SHELL_ESCALATION_UNCERTAIN", review_result.reason)
                                pending_approval.append(
                                    (
                                        idx,
                                        tool_call,
                                        permission_type,
                                        f"Shell command needs review: {review_result.reason}",
                                        extra_ctx,
                                    )
                                )
                                continue
                            record_decision(
                                tool_name, "SHELL_ESCALATION_ALLOW", "shell command cleared by escalation check"
                            )

                record_decision(tool_name, "ALLOW", reason)
                auto_approved.append((idx, tool_call))
                record_approval()
                continue

        if action == PermissionAction.DENY:
            logger.warning("[SECURITY] Tool %s DENIED: %s", tool_name, reason)
            record_decision(tool_name, "DENY", reason)
            hint = record_denial(tool_name)
            auto_denied.append(
                (
                    idx,
                    tool_call,
                    f"Tool execution denied by security policy: {reason}{hint}",
                )
            )
            continue

        if is_cron:
            from myrm_agent_harness.agent.security.types import DEFAULT_CAPABILITIES

            if config.capabilities == DEFAULT_CAPABILITIES:
                logger.warning(
                    "[CRON_POLICY] Tool %s ASK downgraded to DENY in cron session %s: "
                    "no explicit capability declaration (fail-closed)",
                    tool_name,
                    session_key,
                )
                record_decision(
                    tool_name,
                    "CRON_DENY",
                    "cron fail-closed: no explicit capability declaration",
                )
                hint = record_denial(tool_name)
                auto_denied.append(
                    (
                        idx,
                        tool_call,
                        f"Tool denied: cron fail-closed policy. "
                        f"This cron job has no explicit capability declaration.{hint}",
                    )
                )
                continue
            logger.warning(
                "[CRON_POLICY] Tool %s ASK promoted to ALLOW in cron session %s: "
                "Capability Fence declaration acts as pre-approval",
                tool_name,
                session_key,
            )
            record_decision(tool_name, "ALLOW", "cron capability pre-approval")
            auto_approved.append((idx, tool_call))
            record_approval()
            continue

        skill_hook_verdict = _evaluate_skill_hooks_for_tool(tool_name, tool_input)
        if skill_hook_verdict is not None:
            if skill_hook_verdict.action == HookAction.BLOCK:
                logger.warning(
                    "[SKILL_HOOK] Tool %s BLOCKED by skill '%s': %s",
                    tool_name,
                    skill_hook_verdict.blocking_skill,
                    skill_hook_verdict.reason,
                )
                record_decision(tool_name, "SKILL_HOOK_BLOCK", skill_hook_verdict.reason)
                hint = record_denial(tool_name)
                auto_denied.append(
                    (
                        idx,
                        tool_call,
                        f"Blocked by skill '{skill_hook_verdict.blocking_skill}': {skill_hook_verdict.reason}{hint}",
                    )
                )
                continue
            if skill_hook_verdict.action == HookAction.REQUIRE_APPROVAL:
                logger.warning(
                    "[SKILL_HOOK] Tool %s requires approval: %s",
                    tool_name,
                    skill_hook_verdict.reason,
                )
                record_decision(tool_name, "SKILL_HOOK_APPROVAL", skill_hook_verdict.reason)
                pending_approval.append(
                    (
                        idx,
                        tool_call,
                        permission_type,
                        f"Skill approval: {skill_hook_verdict.reason}",
                        extra_ctx,
                    )
                )
                continue

        if config.domain_hitl_enabled:
            domains = extract_url_domains(permission_type, tool_input)
            if domains:
                runtime_domains = _get_runtime_domains()
                if all(d in runtime_domains for d in domains):
                    logger.warning(
                        "[DOMAIN_HITL] Auto-allowed %s (runtime domain match: %s)",
                        tool_name,
                        domains,
                    )
                    record_decision(
                        tool_name,
                        "DOMAIN_RUNTIME_ALLOW",
                        f"runtime domain match: {domains}",
                    )
                    auto_approved.append((idx, tool_call))
                    record_approval()
                    continue

        if (
            config.auto_mode_enabled
            and _batch_review._security_reviewer is not None
            and is_threshold_breached() == ThresholdBreach.NONE
        ):
            # Build command representation for the classifier
            if permission_type in ("shell_exec", "code_interpreter"):
                command = str(tool_input.get("command", "")).strip()
                if extra_ctx and "ptc_annotations" in extra_ctx:
                    command = f"{command}\n\n# PTC Annotations: {extra_ctx['ptc_annotations']}"
            else:
                safe_args = _truncate_tool_args(tool_input)
                command = f"Tool: {tool_name}\nArgs: {json.dumps(safe_args, ensure_ascii=False, default=str)}"

            if command:
                review_result = await _run_llm_review(
                    command,
                    workspace_root,
                    intent_context=intent_context,
                    taint_labels=taint_labels,
                    recent_tool_calls=recent_tool_calls,
                    model_id=config.auto_review_model,
                    trusted_domains=config.network_allowlist,
                )
                if review_result is not None:
                    from myrm_agent_harness.agent.security.types import ReviewDecision

                    if review_result.decision == ReviewDecision.ALLOW:
                        logger.info(
                            "[LLM_REVIEW] Auto-allowed %s: %s",
                            tool_name,
                            review_result.reason,
                        )
                        record_decision(tool_name, "LLM_REVIEW_ALLOW", review_result.reason)
                        auto_approved.append((idx, tool_call))
                        record_approval()
                        continue
                    if review_result.decision == ReviewDecision.DENY:
                        logger.warning(
                            "[LLM_REVIEW] Denied %s: %s",
                            tool_name,
                            review_result.reason,
                        )
                        record_decision(tool_name, "LLM_REVIEW_DENY", review_result.reason)
                        hint = record_denial(tool_name)
                        auto_denied.append(
                            (
                                idx,
                                tool_call,
                                f"Denied by security review: {review_result.reason}{hint}",
                            )
                        )
                        continue
                    record_decision(tool_name, "LLM_REVIEW_UNCERTAIN", review_result.reason)
                    reason = f"{reason}\n\nAI Security Reviewer: {review_result.reason}"

        elif config.auto_mode_enabled and is_threshold_breached() != ThresholdBreach.NONE:
            breach = is_threshold_breached()
            logger.warning(
                "[AUTO_MODE_SUSPENDED] Denial threshold breached (%s) — "
                "tool %s falling through to HITL approval (session: %s)",
                breach.value,
                tool_name,
                session_key,
            )
            record_decision(tool_name, "AUTO_MODE_SUSPENDED", f"denial threshold: {breach.value}")

        pending_approval.append((idx, tool_call, permission_type, reason, extra_ctx))

    return auto_approved, auto_denied, pending_approval


_DEFAULT_APPROVAL_TIMEOUT_SECONDS = 300
_DEFAULT_TIMEOUT_BEHAVIOR = "deny"
