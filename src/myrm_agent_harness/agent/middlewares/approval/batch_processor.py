"""Batch Processor for Agent Security Approvals.

Handles the batch processing of tool calls, including security evaluation,
allowlist checking, and generation of approval requests.

[INPUT]
- agent.security.approval_flow::DEFAULT_USER_ID, get_allowlist (POS: Core component for "Always Allow" feature in Human-in-the-Loop approval system.)
- agent.security.guards.skill_approval_hook::HookAction, SkillApprovalHook, SkillHookVerdict (POS: Integrated into tool_interceptor_middleware between the onion policy engine (L1-L3) and HITL approval. When a skill returns require_approval, the request is forwarded to the existing HITL approval flow.)
- agent.security.script_operand_verifier::compute_file_content_digest, extract_script_file_operand (POS: TOCTOU Defense script operand extraction and sha256 snapshotting.)
- agent.security.tool_registry::resolve_permission_type, resolve_safety_metadata (POS: Maps tool names to abstract permission types and provides safety metadata for MCP tools.)
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
from myrm_agent_harness.agent.security.path_security import (
    is_protected_instruction_file,
)
from myrm_agent_harness.agent.security.tool_registry import (
    resolve_permission_type,
    resolve_safety_metadata,
)
from myrm_agent_harness.agent.security.types import (
    PermissionAction,
    RecentToolCall,
    SecurityConfig,
)
from myrm_agent_harness.core.security.spend_governance import (
    compute_action_digest,
    compute_script_content_hash,
    extract_script_file_target,
    is_financial_or_spend_tool,
    is_irreversible_social_action,
    parse_spend_amount,
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
from .helpers import (
    ThresholdBreach,
    is_threshold_breached,
    record_approval,
    record_denial,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Re-export for backward compatibility
__all__ = [
    "apply_approval_decisions",
    "build_interrupt_payload",
    "evaluate_tool_batch",
    "is_yolo_mode_active",
    "register_security_reviewer",
    "reset_runtime_domains",
]


def is_yolo_mode_active(config: SecurityConfig, *, session_key: str = "") -> bool:
    """Return True when YOLO is enabled and optional timeout has not expired."""
    if not config.yolo_mode_enabled:
        return False
    if config.yolo_mode_timeout and config.yolo_mode_enabled_at is not None:
        elapsed = time.time() - config.yolo_mode_enabled_at
        if elapsed > config.yolo_mode_timeout:
            if session_key:
                logger.warning(
                    "[YOLO] YOLO mode expired after %ds (session: %s)",
                    config.yolo_mode_timeout,
                    session_key,
                )
            return False
    return True


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
    *,
    is_interactive: bool = True,
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

    from myrm_agent_harness.agent.middlewares._session_context import (
        get_agent_primary_model_slug,
        get_managed_approval_policy,
    )
    from myrm_agent_harness.agent.security.managed_policy_gates import (
        effective_auto_mode_enabled,
        yolo_allowed_for_model,
    )
    from myrm_agent_harness.agent.security.managed_policy_gates import (
        honor_allowlist as map_honor_allowlist,
    )

    map_policy = get_managed_approval_policy()
    agent_primary_model = get_agent_primary_model_slug()
    auto_mode_enabled = effective_auto_mode_enabled(
        config, map_policy, agent_primary_model
    )

    if is_yolo_mode_active(config, session_key=session_key) and yolo_allowed_for_model(
        map_policy, agent_primary_model
    ):
        suffix = (
            ""
            if not config.yolo_mode_timeout
            else f" (expires in {config.yolo_mode_timeout}s)"
        )
        logger.info(
            "[YOLO] Auto-approving tool calls%s (session: %s)",
            suffix,
            session_key,
        )
        for idx, tool_call in enumerate(tool_calls):
            tool_name = tool_call.get("name", "unknown")
            tool_input: dict[str, object] = tool_call.get("args", {})
            permission_type = resolve_permission_type(tool_name, tool_input)
            action, reason = evaluate_tool_call(
                permission_type,
                tool_input,
                config,
                workspace_root=workspace_root,
                tool_name=tool_name,
            )
            if action == PermissionAction.DENY:
                logger.warning(
                    "[YOLO] Tool %s DENIED despite YOLO mode: %s (session: %s)",
                    tool_name,
                    reason,
                    session_key,
                )
                record_decision(tool_name, "YOLO_DENY_OVERRIDE", reason)
                auto_denied.append(
                    (
                        idx,
                        tool_call,
                        f"Tool execution denied by security policy: {reason}",
                    )
                )
            elif is_financial_or_spend_tool(tool_name, tool_input):
                logger.warning(
                    "[YOLO_FINANCIAL_GATE] Tool %s blocked from YOLO auto-approval (financial spend detected)",
                    tool_name,
                )
                record_decision(
                    tool_name,
                    "YOLO_FINANCIAL_GATE_BLOCKED",
                    "Financial spend tools are immune to YOLO auto-approval",
                )
                spend_amt, spend_cur = parse_spend_amount(tool_input)
                spend_digest = compute_action_digest(tool_name, tool_input)
                spend_ctx: dict[str, object] = {
                    "is_spend": True,
                    "spend_amount": spend_amt,
                    "spend_currency": spend_cur,
                    "action_digest": spend_digest,
                    "high_risk": True,
                    "hide_allow_always": True,
                }
                disp_amt = f"{spend_amt:.2f} {spend_cur}" if spend_amt is not None else "transaction"
                pending_approval.append(
                    (
                        idx,
                        tool_call,
                        permission_type,
                        f"Financial spend operation requires explicit approval ({disp_amt})",
                        spend_ctx,
                    )
                )
            elif is_irreversible_social_action(tool_name, tool_input):
                logger.warning(
                    "[YOLO_SOCIAL_IRREVERSIBLE_GATE] Tool %s blocked from YOLO auto-approval (socially irreversible)",
                    tool_name,
                )
                record_decision(
                    tool_name,
                    "YOLO_SOCIAL_IRREVERSIBLE_BLOCKED",
                    "Socially irreversible operations are immune to YOLO auto-approval",
                )
                irreversible_ctx: dict[str, object] = {
                    "socially_irreversible": True,
                    "high_risk": True,
                    "hide_allow_always": True,
                }
                pending_approval.append(
                    (
                        idx,
                        tool_call,
                        permission_type,
                        f"Socially irreversible operation ({tool_name}) requires explicit human approval",
                        irreversible_ctx,
                    )
                )
            else:
                record_decision(tool_name, "YOLO_AUTO_APPROVE", "YOLO mode enabled")
                auto_approved.append((idx, tool_call))
        return auto_approved, auto_denied, pending_approval

    from myrm_agent_harness.core.security.device_policy import evaluate_batch_risk
    from myrm_agent_harness.core.security.remote_ops_ledger import derive_recovery_hint

    batch_assessment = evaluate_batch_risk(
        tool_calls,
        permission_resolver=resolve_permission_type,
    )

    for idx, tool_call in enumerate(tool_calls):
        tool_name = tool_call.get("name", "unknown")
        tool_input: dict[str, object] = tool_call.get("args", {})

        permission_type = resolve_permission_type(tool_name, tool_input)
        action, reason = evaluate_tool_call(
            permission_type,
            tool_input,
            config,
            workspace_root=workspace_root,
            tool_name=tool_name,
        )

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
                    path_action, path_reason = check_path_policy(
                        ptc_path, config.path_policy, workspace_root
                    )
                    if path_action == PermissionAction.DENY:
                        action = PermissionAction.DENY
                        reason = f"PTC {path_reason}"
                    elif (
                        path_action == PermissionAction.ASK
                        and action != PermissionAction.DENY
                    ):
                        action = PermissionAction.ASK
                        reason = f"PTC {path_reason}"

                # Fast-Path Auto-Approve Logic
                if (
                    action == PermissionAction.ASK
                    and ptc_safety
                    and ptc_safety.is_read_only
                    and not ptc_safety.is_open_world
                    and not ptc_safety.is_destructive
                ):
                    action = PermissionAction.ALLOW
                    reason = f"Fast-Path Auto-Approve for read-only MCP tool: {ptc_tool_name_full}"

        # Fast-Path Auto-Approve for read-only MCP tools (non-PTC path).
        # MCP annotations (readOnlyHint etc.) are registered into
        # _PTC_TOOL_FLAT_INDEX at session init; leverage them here so
        # read-only MCP tools skip the HITL prompt without user config.
        if action == PermissionAction.ASK and permission_type == "mcp_invoke":
            mcp_safety = resolve_safety_metadata(tool_name)
            if (
                mcp_safety.is_read_only
                and not mcp_safety.is_open_world
                and not mcp_safety.is_destructive
            ):
                action = PermissionAction.ALLOW
                reason = f"Fast-Path Auto-Approve for read-only MCP tool: {tool_name}"

        # Allowlist check: if still ASK, check if the tool is in user's allowlist
        if action == PermissionAction.ASK:
            from myrm_agent_harness.agent.middlewares._session_context import (
                get_agent_id,
                get_approval_session,
                get_approval_user_id,
            )

            allowlist = get_allowlist()
            user_id = get_approval_user_id() or DEFAULT_USER_ID
            current_agent_id = get_agent_id() or None
            current_session_id = get_approval_session() or None
            await allowlist.load_user(user_id)
            effective_tool_name = (
                extra_ctx.get("ptc_tool_name_full", tool_name)
                if extra_ctx
                else tool_name
            )
            args_hash = args_hashes.get(idx)
            from myrm_agent_harness.agent.security.command_allowlist_pattern import (
                extract_shell_command,
            )

            shell_command = extract_shell_command(tool_input)

            if action == PermissionAction.ASK and shell_command and permission_type == "shell_exec":
                from myrm_agent_harness.agent.security.workspace_trust.context import (
                    get_repo_command_prefixes,
                    get_workspace_trust_level,
                )
                from myrm_agent_harness.agent.security.workspace_trust.gate import (
                    matches_repo_command_prefix,
                )
                from myrm_agent_harness.agent.security.workspace_trust.types import (
                    WorkspaceTrustLevel,
                )

                if get_workspace_trust_level() == WorkspaceTrustLevel.TRUSTED:
                    prefixes = get_repo_command_prefixes()
                    if matches_repo_command_prefix(shell_command, prefixes):
                        action = PermissionAction.ALLOW
                        reason = "Repo-declared command prefix auto-approve"
                        record_decision(tool_name, "REPO_PREFIX_AUTO_APPROVE", reason)

            matching_allowlist_entry = allowlist.find_matching_entry(
                user_id,
                permission_type,
                effective_tool_name,
                args_hash,
                command=shell_command,
                agent_id=current_agent_id,
                session_id=current_session_id,
            )
            allowlist_would_match = matching_allowlist_entry is not None
            # If batch assessment marked this batch as high-risk/dual insurance, block allowlist bypass
            if allowlist_would_match and batch_assessment.allow_always_blocked:
                record_decision(
                    tool_name,
                    "BATCH_RISK_DUAL_INSURANCE_ESCALATED",
                    f"batch high-risk dual insurance blocked allowlist bypass: {effective_tool_name}",
                )
                allowlist_would_match = False
            elif allowlist_would_match and is_financial_or_spend_tool(tool_name, tool_input):
                record_decision(
                    tool_name,
                    "FINANCIAL_GATE_ALLOWLIST_BLOCKED",
                    f"Financial spend tools cannot be bypassed via allowlist: {effective_tool_name}",
                )
                allowlist_would_match = False
            elif allowlist_would_match and is_irreversible_social_action(tool_name, tool_input):
                record_decision(
                    tool_name,
                    "IRREVERSIBLE_ACTION_ALLOWLIST_BLOCKED",
                    f"Socially irreversible actions cannot be bypassed via allowlist: {effective_tool_name}",
                )
                allowlist_would_match = False
            elif allowlist_would_match and (
                "Protected instruction file write requires human approval" in reason
                or (
                    permission_type in ("file_write", "fs_mutation")
                    and is_protected_instruction_file(str(tool_input.get("path", "") or tool_input.get("file_path", "") or tool_input.get("filepath", "")))
                )
            ):
                record_decision(
                    tool_name,
                    "PROTECTED_INSTRUCTION_ALLOWLIST_BLOCKED",
                    f"Protected instruction files cannot be bypassed via allowlist: {effective_tool_name}",
                )
                allowlist_would_match = False

            if not map_honor_allowlist(map_policy, agent_primary_model):
                if allowlist_would_match:
                    record_decision(
                        tool_name,
                        "MAP_ALLOWLIST_SKIPPED",
                        f"org policy ignores allowlist for model {agent_primary_model}",
                    )
            elif allowlist_would_match:
                action = PermissionAction.ALLOW
                if (
                    matching_allowlist_entry is not None
                    and matching_allowlist_entry.session_id is not None
                ):
                    reason = f"Allowlist session-scoped auto-approve: {effective_tool_name}"
                    record_decision(tool_name, "ALLOWLIST_SESSION_ALLOW", reason)
                else:
                    reason = f"Allowlist auto-approve: {effective_tool_name}"
                    record_decision(tool_name, "ALLOWLIST_AUTO_APPROVE", reason)

        if action == PermissionAction.ALLOW and is_irreversible_social_action(tool_name, tool_input):
            action = PermissionAction.ASK
            reason = f"Socially irreversible operation ({tool_name}) requires explicit human approval"
            extra_ctx = extra_ctx or {}
            extra_ctx["socially_irreversible"] = True
            extra_ctx["high_risk"] = True
            extra_ctx["hide_allow_always"] = True
            record_decision(tool_name, "SOCIAL_IRREVERSIBLE_GATE_ESCALATED", reason)

        if action == PermissionAction.ALLOW and auto_mode_enabled and is_threshold_breached(session_key) != ThresholdBreach.NONE:
            breach = is_threshold_breached(session_key)
            action = PermissionAction.ASK
            reason = f"Auto-mode suspended ({breach.value} denial threshold breached) — explicit approval required"
            extra_ctx = extra_ctx or {}
            extra_ctx["auto_mode_suspended"] = breach.value
            extra_ctx["high_risk"] = True
            extra_ctx["hide_allow_always"] = True
            record_decision(tool_name, "AUTO_MODE_SUSPENDED_ALLOW_ESCALATED", reason)

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
                                ", ".join(truncated_sources)
                                + f" ... and {len(sources_list) - 5} more sources"
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
                extra_ctx = extra_ctx or {}
                extra_ctx["high_risk"] = True

                # Smart Intent Guard: Try LLM review for taint conflict if enabled
                if (
                    auto_mode_enabled
                    and _batch_review._security_reviewer is not None
                    and is_threshold_breached(session_key) == ThresholdBreach.NONE
                    and not is_irreversible_social_action(tool_name, tool_input)
                ):
                    safe_tool_input = _truncate_tool_args(tool_input)
                    command_repr = (
                        f"Tool: {tool_name}\nArgs: {json.dumps(safe_tool_input)}"
                    )
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
                            record_decision(
                                tool_name, "LLM_REVIEW_ALLOW", review_result.reason
                            )
                            auto_approved.append((idx, tool_call))
                            record_approval(session_key)
                            continue
                        if review_result.decision == ReviewDecision.DENY:
                            logger.warning(
                                "[LLM_REVIEW] Denied tainted %s: %s",
                                tool_name,
                                review_result.reason,
                            )
                            record_decision(
                                tool_name, "LLM_REVIEW_DENY", review_result.reason
                            )
                            hint = record_denial(tool_name, session_key)
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
                            reason = f"{reason}\n\n AI Security Reviewer Note:\n{review_result.reason}"
                            extra_ctx = extra_ctx or {}
                            extra_ctx["high_risk"] = True
            else:
                # Auto Mode outbound check: external CLI actions that pass
                # the deterministic engine as ALLOW still need Classifier review
                # to prevent prompt-injection → malicious-delegation attacks.
                if (
                    permission_type == "invoke_external_agent"
                    and auto_mode_enabled
                    and _batch_review._security_reviewer is not None
                    and is_threshold_breached(session_key) == ThresholdBreach.NONE
                ):
                    safe_tool_input = _truncate_tool_args(tool_input)
                    command_repr = f"Tool: {tool_name}\nArgs: {json.dumps(safe_tool_input, ensure_ascii=False, default=str)}"
                    review_result = await _run_llm_review(
                        command_repr,
                        workspace_root,
                        intent_context=intent_context,
                        recent_tool_calls=recent_tool_calls,
                        model_id=config.auto_review_model,
                        trusted_domains=config.network_allowlist,
                    )
                    if review_result is not None:
                        from myrm_agent_harness.agent.security.types import (
                            ReviewDecision,
                        )

                        if review_result.decision == ReviewDecision.DENY:
                            logger.warning(
                                "[OUTBOUND_CHECK] Denied delegation %s: %s",
                                tool_name,
                                review_result.reason,
                            )
                            record_decision(
                                tool_name, "OUTBOUND_DENY", review_result.reason
                            )
                            hint = record_denial(tool_name, session_key)
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
                            record_decision(
                                tool_name, "OUTBOUND_UNCERTAIN", review_result.reason
                            )
                            extra_ctx = extra_ctx or {}
                            extra_ctx["high_risk"] = True
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
                        record_decision(
                            tool_name,
                            "OUTBOUND_ALLOW",
                            "delegation cleared by outbound check",
                        )

                # Auto Mode shell escalation: shell_exec/code_interpreter actions
                # that pass the deterministic engine as ALLOW still need Classifier
                # review when the command is not trivially safe (Risk Classifier UNKNOWN).
                # Prevents user-defined broad ALLOW rules from bypassing Classifier.
                if (
                    permission_type in ("shell_exec", "code_interpreter")
                    and auto_mode_enabled
                    and _batch_review._security_reviewer is not None
                    and is_threshold_breached(session_key) == ThresholdBreach.NONE
                ):
                    from myrm_agent_harness.toolkits.code_execution.security.risk_classifier import (
                        CommandRiskLevel,
                        classify_command_risk,
                    )

                    shell_cmd = str(
                        tool_input.get("command", "")
                        or tool_input.get("code", "")
                        or tool_input.get("data", "")
                    ).strip()
                    if (
                        shell_cmd
                        and (
                            getattr(config, "classify_all_shell_in_auto_mode", False)
                            or classify_command_risk(shell_cmd) != CommandRiskLevel.SAFE
                        )
                    ):
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
                            from myrm_agent_harness.agent.security.types import (
                                ReviewDecision,
                            )

                            if review_result.decision == ReviewDecision.DENY:
                                logger.warning(
                                    "[SHELL_ESCALATION] Denied %s (ALLOW→DENY): %s",
                                    tool_name,
                                    review_result.reason,
                                )
                                record_decision(
                                    tool_name,
                                    "SHELL_ESCALATION_DENY",
                                    review_result.reason,
                                )
                                hint = record_denial(tool_name, session_key)
                                if is_interactive:
                                    extra_ctx = extra_ctx or {}
                                    extra_ctx["smart_denied"] = True
                                    extra_ctx["reviewer_reason"] = review_result.reason
                                    reason = f"AI Security Reviewer recommends denial: {review_result.reason}"
                                    pending_approval.append(
                                        (idx, tool_call, permission_type, reason, extra_ctx)
                                    )
                                else:
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
                                record_decision(
                                    tool_name,
                                    "SHELL_ESCALATION_UNCERTAIN",
                                    review_result.reason,
                                )
                                extra_ctx = extra_ctx or {}
                                extra_ctx["high_risk"] = True
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
                                tool_name,
                                "SHELL_ESCALATION_ALLOW",
                                "shell command cleared by escalation check",
                            )

                if reason.startswith("Sandbox-aware") or (
                    getattr(config, "is_sandbox", False)
                    and permission_type in ("shell_exec", "code_interpreter")
                ):
                    record_decision(tool_name, "SANDBOX_AUTO_BYPASS", reason)
                else:
                    record_decision(tool_name, "ALLOW", reason)
                auto_approved.append((idx, tool_call))
                record_approval(session_key)
                continue

        if action == PermissionAction.DENY:
            logger.warning("[SECURITY] Tool %s DENIED: %s", tool_name, reason)
            record_decision(tool_name, "DENY", reason)
            hint = record_denial(tool_name, session_key)
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
                hint = record_denial(tool_name, session_key)
                auto_denied.append(
                    (
                        idx,
                        tool_call,
                        f"Tool denied: cron fail-closed policy. "
                        f"This cron job has no explicit capability declaration.{hint}",
                    )
                )
                continue
            shell_cmd = str(
                tool_input.get("command", "")
                or tool_input.get("code", "")
                or tool_input.get("data", "")
            ).strip()
            if permission_type in ("shell_exec", "code_interpreter") and shell_cmd:
                from myrm_agent_harness.toolkits.code_execution.security.shell_command_analyzer import (
                    is_integration_mutation_command,
                )

                if is_integration_mutation_command(shell_cmd):
                    logger.warning(
                        "[CRON_POLICY] Tool %s DENIED in cron session %s: "
                        "integration write mutations are never pre-approved",
                        tool_name,
                        session_key,
                    )
                    record_decision(
                        tool_name,
                        "CRON_DENY",
                        "cron fail-closed: integration write mutation",
                    )
                    hint = record_denial(tool_name, session_key)
                    auto_denied.append(
                        (
                            idx,
                            tool_call,
                            f"Tool denied: cron jobs cannot auto-approve Google/integration write operations.{hint}",
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
            record_approval(session_key)
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
                record_decision(
                    tool_name, "SKILL_HOOK_BLOCK", skill_hook_verdict.reason
                )
                hint = record_denial(tool_name, session_key)
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
                record_decision(
                    tool_name, "SKILL_HOOK_APPROVAL", skill_hook_verdict.reason
                )
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
            auto_mode_enabled
            and _batch_review._security_reviewer is not None
            and is_threshold_breached() == ThresholdBreach.NONE
            and not is_irreversible_social_action(tool_name, tool_input)
        ):
            # Build command representation for the classifier
            if permission_type in ("shell_exec", "code_interpreter"):
                command = str(
                    tool_input.get("command", "")
                    or tool_input.get("code", "")
                    or tool_input.get("data", "")
                ).strip()
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
                        record_decision(
                            tool_name, "LLM_REVIEW_ALLOW", review_result.reason
                        )
                        auto_approved.append((idx, tool_call))
                        record_approval(session_key)
                        continue
                    if review_result.decision == ReviewDecision.DENY:
                        logger.warning(
                            "[LLM_REVIEW] Denied %s: %s",
                            tool_name,
                            review_result.reason,
                        )
                        record_decision(
                            tool_name, "LLM_REVIEW_DENY", review_result.reason
                        )
                        if is_interactive:
                            extra_ctx = extra_ctx or {}
                            extra_ctx["smart_denied"] = True
                            extra_ctx["reviewer_reason"] = review_result.reason
                            reason = f"AI Security Reviewer recommends denial: {review_result.reason}"
                            pending_approval.append(
                                (idx, tool_call, permission_type, reason, extra_ctx)
                            )
                        else:
                            hint = record_denial(tool_name, session_key)
                            auto_denied.append(
                                (
                                    idx,
                                    tool_call,
                                    f"Denied by security review: {review_result.reason}{hint}",
                                )
                            )
                        continue
                    record_decision(
                        tool_name, "LLM_REVIEW_UNCERTAIN", review_result.reason
                    )
                    reason = f"{reason}\n\nAI Security Reviewer: {review_result.reason}"
                    extra_ctx = extra_ctx or {}
                    extra_ctx["high_risk"] = True

        elif auto_mode_enabled and is_threshold_breached(session_key) != ThresholdBreach.NONE:
            breach = is_threshold_breached(session_key)
            logger.warning(
                "[AUTO_MODE_SUSPENDED] Denial threshold breached (%s) — "
                "tool %s falling through to HITL approval (session: %s)",
                breach.value,
                tool_name,
                session_key,
            )
            record_decision(
                tool_name, "AUTO_MODE_SUSPENDED", f"denial threshold: {breach.value}"
            )
            extra_ctx = extra_ctx or {}
            extra_ctx["high_risk"] = True
            extra_ctx["auto_mode_suspended"] = breach.value

        if reason.startswith("Shell threat"):
            extra_ctx = extra_ctx or {}
            extra_ctx["high_risk"] = True

        if batch_assessment.is_high_risk:
            extra_ctx = extra_ctx or {}
            extra_ctx["high_risk"] = True
            extra_ctx["hide_allow_always"] = True
            if batch_assessment.requires_dual_insurance:
                extra_ctx["requires_dual_insurance"] = True
            if batch_assessment.reasons:
                extra_ctx["batch_impact_summary"] = {
                    "batch_size": batch_assessment.batch_size,
                    "mutating_count": batch_assessment.mutating_count,
                    "reasons": list(batch_assessment.reasons),
                    "impacted_targets": list(batch_assessment.impacted_targets[:10]),
                }

        recovery_hint = derive_recovery_hint(tool_name, tool_input)
        if recovery_hint:
            extra_ctx = extra_ctx or {}
            extra_ctx["recovery_hint"] = (
                recovery_hint.recovery_command or recovery_hint.description
            )

        if is_financial_or_spend_tool(tool_name, tool_input):
            extra_ctx = extra_ctx or {}
            amt, cur = parse_spend_amount(tool_input)
            extra_ctx["is_spend"] = True
            extra_ctx["spend_amount"] = amt
            extra_ctx["spend_currency"] = cur
            extra_ctx["action_digest"] = compute_action_digest(tool_name, tool_input)
            extra_ctx["high_risk"] = True
            extra_ctx["hide_allow_always"] = True
        elif is_irreversible_social_action(tool_name, tool_input):
            extra_ctx = extra_ctx or {}
            extra_ctx["is_irreversible"] = True
            extra_ctx["socially_irreversible"] = True
            extra_ctx["action_digest"] = compute_action_digest(tool_name, tool_input)
            extra_ctx["high_risk"] = True
            extra_ctx["hide_allow_always"] = True

        raw_path_arg = str(
            tool_input.get("path", "")
            or tool_input.get("file_path", "")
            or tool_input.get("filepath", "")
        ).strip()
        if (
            "Protected instruction file write requires human approval" in reason
            or (raw_path_arg and is_protected_instruction_file(raw_path_arg))
        ):
            extra_ctx = extra_ctx or {}
            extra_ctx["protected_instruction"] = True
            extra_ctx["hide_allow_always"] = True
            extra_ctx["high_risk"] = True
            record_decision(
                tool_name,
                "PROTECTED_INSTRUCTION_ATTEMPT",
                f"Attempted mutation of protected instruction file: {raw_path_arg}",
            )
            logger.warning(
                "[PROTECTED_INSTRUCTION] Gate triggered for %s (path=%s): hide_allow_always enforced",
                tool_name,
                raw_path_arg,
            )

        script_target = extract_script_file_target(tool_name, tool_input)
        if script_target:
            script_hash = compute_script_content_hash(script_target)
            if script_hash:
                extra_ctx = extra_ctx or {}
                extra_ctx["script_target"] = script_target
                extra_ctx["script_content_hash"] = script_hash
                extra_ctx["high_risk"] = True


        # TOCTOU Defense: extract mutable script operand and compute content digest (CVE-2026-32921)
        if permission_type in ("shell_exec", "code_interpreter") or tool_name in (
            "bash_code_execute_tool",
            "execute_code",
        ):
            shell_cmd_for_snapshot = str(
                tool_input.get("command", "")
                or tool_input.get("code", "")
                or tool_input.get("script", "")
                or tool_input.get("cmd", "")
            ).strip()
            if shell_cmd_for_snapshot:
                from myrm_agent_harness.agent.security.script_operand_verifier import (
                    compute_file_content_digest,
                    extract_script_file_operand,
                )

                script_path = extract_script_file_operand(
                    shell_cmd_for_snapshot, workspace_root=workspace_root
                )
                if script_path:
                    script_digest = compute_file_content_digest(script_path)
                    if script_digest:
                        extra_ctx = extra_ctx or {}
                        extra_ctx["script_operand_path"] = script_path
                        extra_ctx["script_operand_hash"] = script_digest
                        extra_ctx["hide_allow_always"] = True
                        logger.info(
                            "[SCRIPT_OPERAND] Snapshotted script operand for %s: path=%s, sha256=%s",
                            tool_name,
                            script_path,
                            script_digest[:12],
                        )

        pending_approval.append((idx, tool_call, permission_type, reason, extra_ctx))


    return auto_approved, auto_denied, pending_approval
