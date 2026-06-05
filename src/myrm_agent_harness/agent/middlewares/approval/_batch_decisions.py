"""Batch approval decision handling — interrupt payload and decision application.

[INPUT]
- agent.security (POS: security types, approval flow, audit, engine)

[OUTPUT]
- build_interrupt_payload: Build LangChain-standard interrupt payload for batch approval (includes optional command_spans for shell tools).
- apply_approval_decisions: Apply user decisions to tool_calls and generate ToolMessages (blocks unsafe shell edits).

[POS]
Batch approval decision handling — interrupt payload construction and decision application.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from langchain_core.messages import AIMessage, ToolCall, ToolMessage

from myrm_agent_harness.agent.security.approval_flow import DEFAULT_USER_ID
from myrm_agent_harness.agent.security.audit import record_decision
from myrm_agent_harness.agent.security.engine import extract_url_domains
from myrm_agent_harness.agent.security.redact import redact_for_display
from myrm_agent_harness.agent.security.types import SecurityConfig

from .helpers import add_to_allowlist_if_needed, record_denial

logger = logging.getLogger(__name__)

__all__ = ["apply_approval_decisions", "build_interrupt_payload"]

_DEFAULT_APPROVAL_TIMEOUT_SECONDS = 600
_DEFAULT_TIMEOUT_BEHAVIOR = "deny"

_EDIT_REAPPROVAL_MESSAGE = (
    "Edited command requires new approval: modified shell commands with "
    "non-safe risk must be re-submitted by the agent."
)

_SHELL_EDIT_PERMISSION_TYPES = frozenset({"shell_exec", "code_interpreter"})


def _edited_shell_edit_block_reason(
    tool_name: str,
    permission_type: str,
    original_args: dict[str, object],
    edited_args: dict[str, object],
) -> str | None:
    """Return a rejection reason when an edited shell command must be re-approved."""
    from myrm_agent_harness.toolkits.code_execution.security.command_explainer.extract import (
        extract_shell_command_text,
        is_shell_approval_tool,
    )
    from myrm_agent_harness.toolkits.code_execution.security.risk_classifier import (
        CommandRiskLevel,
        classify_command_risk,
    )

    if permission_type not in _SHELL_EDIT_PERMISSION_TYPES:
        return None
    if not is_shell_approval_tool(tool_name):
        return None

    original_cmd = extract_shell_command_text(original_args)
    edited_cmd = extract_shell_command_text(edited_args)
    if not edited_cmd or original_cmd.strip() == edited_cmd.strip():
        return None
    if classify_command_risk(edited_cmd) == CommandRiskLevel.SAFE:
        return None
    return _EDIT_REAPPROVAL_MESSAGE


def build_interrupt_payload(
    pending_approval: list[tuple[int, ToolCall, str, str, dict[str, Any] | None]],
    session_key: str,
    *,
    approval_timeout_seconds: int | None = None,
    timeout_behavior: str = _DEFAULT_TIMEOUT_BEHAVIOR,
    workspace_root: str | None = None,
) -> tuple[dict[str, Any], list[int]]:
    """Build LangChain-standard interrupt payload for batch approval.

    Args:
        pending_approval: list of (idx, tool_call, permission_type, reason, extra_ctx)
        session_key: session identifier for routing
        approval_timeout_seconds: seconds before auto-resolution (from SecurityConfig)
        timeout_behavior: "deny" or "allow" — action taken when timeout expires

    Returns: (interrupt_payload, interrupt_indices)
    """
    action_requests = []
    review_configs = []
    interrupt_indices = []

    for idx, tool_call, permission_type, reason, extra_ctx in pending_approval:
        tool_name = tool_call.get("name", "unknown")
        tool_input = tool_call.get("args", {})

        action_name = tool_name
        if extra_ctx and "ptc_tool_name_full" in extra_ctx:
            action_name = extra_ctx["ptc_tool_name_full"]

        redacted_args = redact_for_display(tool_input)
        action_request: dict[str, object] = {
            "action": action_name,
            "args": redacted_args,
            "description": reason,
        }
        if extra_ctx and "ptc_annotations" in extra_ctx:
            action_request["ptc_annotations"] = extra_ctx["ptc_annotations"]

        domains = extract_url_domains(permission_type, tool_input)
        if domains:
            action_request["domains"] = domains

        from myrm_agent_harness.toolkits.code_execution.security.command_explainer.extract import (
            build_shell_approval_fields,
        )

        action_request.update(build_shell_approval_fields(tool_name, redacted_args))

        review_config: dict[str, object] = {
            "allowedDecisions": ["approve", "reject", "edit"],
        }
        if domains:
            review_config["domainApproval"] = True

        action_requests.append(action_request)
        review_configs.append(review_config)
        interrupt_indices.append(idx)

    logger.info(
        "[BATCH_APPROVAL] Triggering interrupt for %d tools: %s",
        len(action_requests),
        [req["action"] for req in action_requests],
    )

    has_handover = any(perm_type == "browser_human_handover" for _, _, perm_type, _, _ in pending_approval)
    display_mode = "handover" if has_handover else "approval"

    effective_timeout = approval_timeout_seconds or _DEFAULT_APPROVAL_TIMEOUT_SECONDS
    expires_at = time.time() + effective_timeout
    request_id = str(uuid.uuid4())

    payload = {
        "actionRequests": action_requests,
        "reviewConfigs": review_configs,
        "extensions": {
            "timeout": {
                "seconds": effective_timeout,
                "expiresAt": expires_at,
                "behavior": timeout_behavior,
            },
            "approval": {
                "requestId": request_id,
                "sessionKey": session_key,
                "batchSize": len(action_requests),
            },
            "displayMode": display_mode,
        },
    }
    if workspace_root:
        payload["extensions"]["workspaceRoot"] = workspace_root

    return payload, interrupt_indices


async def apply_approval_decisions(
    decisions: list[dict[str, Any]],
    last_ai_msg: AIMessage,
    auto_denied: list[tuple[int, ToolCall, str]],
    pending_approval: list[tuple[int, ToolCall, str, str, dict[str, Any] | None]],
    interrupt_indices: list[int],
    args_hashes: dict[int, str | None],
    config: SecurityConfig | None = None,
) -> tuple[list[ToolCall], list[ToolMessage]]:
    """Apply user decisions to tool_calls and generate ToolMessages.

    When *config* is provided and ``domain_hitl_enabled`` is True, handles
    ``allowDomain`` extensions by adding approved domains to the session-scoped
    runtime allowlist.

    Returns: (revised_tool_calls, artificial_tool_messages)
    """
    from ._batch_review import _get_runtime_domains

    revised_tool_calls: list[ToolCall] = []
    artificial_tool_messages: list[ToolMessage] = []
    decision_idx = 0

    for idx, tool_call in enumerate(last_ai_msg.tool_calls):
        denied = next(((d_idx, tc, msg) for d_idx, tc, msg in auto_denied if d_idx == idx), None)
        if denied:
            _, _, error_msg = denied
            artificial_tool_messages.append(
                ToolMessage(
                    content=error_msg,
                    name=tool_call.get("name", "unknown"),
                    tool_call_id=tool_call.get("id", ""),
                    status="error",
                )
            )
            continue

        if idx in interrupt_indices:
            decision = decisions[decision_idx]
            decision_idx += 1

            _, _, permission_type, reason, extra_ctx = pending_approval[decision_idx - 1]
            tool_name = tool_call.get("name", "unknown")
            tool_call_id = tool_call.get("id", "")
            allowlist_tool_name = extra_ctx.get("ptc_tool_name_full", tool_name) if extra_ctx else tool_name

            decision_type = decision.get("type", "reject")
            extensions = decision.get("extensions", {})
            allow_always = extensions.get("allowAlways", False)
            allow_domain = extensions.get("allowDomain", False)

            logger.info(
                "[APPROVAL] Tool %s decision: type=%s, allow_always=%s, allow_domain=%s",
                tool_name,
                decision_type,
                allow_always,
                allow_domain,
            )

            if decision_type == "approve":
                record_decision(tool_name, "USER_APPROVED", reason)

                if allow_domain and config and config.domain_hitl_enabled:
                    tool_input: dict[str, object] = tool_call.get("args", {})
                    domains = extract_url_domains(permission_type, tool_input)
                    if domains:
                        runtime_domains = _get_runtime_domains()
                        for domain in domains:
                            runtime_domains.add(domain)
                        logger.warning(
                            "[DOMAIN_HITL] User approved domain(s) %s for session",
                            domains,
                        )
                        record_decision(tool_name, "DOMAIN_APPROVED", f"domains: {domains}")

                if allow_always:
                    from myrm_agent_harness.agent.middlewares._session_context import (
                        get_approval_user_id,
                    )

                    user_id = get_approval_user_id() or DEFAULT_USER_ID
                    await add_to_allowlist_if_needed(
                        allow_always,
                        user_id,
                        permission_type,
                        allowlist_tool_name,
                        args_hashes.get(idx),
                    )

                revised_tool_calls.append(tool_call)

            elif decision_type == "edit":
                edited_args = decision.get("args")

                edit_applied = False
                if edited_args is not None:
                    raw_original_args = tool_call.get("args", {})
                    original_args = dict(raw_original_args) if isinstance(raw_original_args, dict) else {}
                    normalized_edited_args = dict(edited_args) if isinstance(edited_args, dict) else {}
                    edit_block_reason = _edited_shell_edit_block_reason(
                        tool_name,
                        permission_type,
                        original_args,
                        normalized_edited_args,
                    )
                    if edit_block_reason is not None:
                        logger.warning(
                            "[APPROVAL] Tool %s: edited shell command blocked",
                            tool_name,
                        )
                        record_decision(tool_name, "USER_EDIT_REJECTED", edit_block_reason)
                        hint = record_denial(tool_name)
                        artificial_tool_messages.append(
                            ToolMessage(
                                content=f"{edit_block_reason}{hint}",
                                name=tool_name,
                                tool_call_id=tool_call_id,
                                status="error",
                            )
                        )
                    else:
                        logger.warning("[APPROVAL] Tool %s: user edited args", tool_name)
                        record_decision(tool_name, "USER_EDITED", reason)
                        revised_tool_calls.append(
                            ToolCall(
                                type="tool_call",
                                name=tool_call.get("name", "unknown"),
                                args=normalized_edited_args,
                                id=tool_call_id,
                            )
                        )
                        edit_applied = True
                else:
                    record_decision(tool_name, "USER_EDITED", reason)
                    revised_tool_calls.append(tool_call)
                    edit_applied = True

                if edit_applied and allow_always:
                    from myrm_agent_harness.agent.middlewares._session_context import (
                        get_approval_user_id,
                    )

                    user_id = get_approval_user_id() or DEFAULT_USER_ID
                    await add_to_allowlist_if_needed(
                        allow_always,
                        user_id,
                        permission_type,
                        allowlist_tool_name,
                        args_hashes.get(idx),
                    )

            else:
                feedback = decision.get("feedback", "User rejected this action.")
                logger.warning("[SECURITY] Tool %s REJECTED by user: %s", tool_name, feedback)
                record_decision(tool_name, "USER_REJECTED", feedback)
                hint = record_denial(tool_name)
                artificial_tool_messages.append(
                    ToolMessage(
                        content=f"Action rejected by user: {feedback}{hint}",
                        name=tool_name,
                        tool_call_id=tool_call_id,
                        status="error",
                    )
                )
        else:
            revised_tool_calls.append(tool_call)

    return revised_tool_calls, artificial_tool_messages
