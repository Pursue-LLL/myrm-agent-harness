"""Shared semantic DOM HITL gate for all browser interaction paths.

[INPUT]
- toolkits.browser.tools._semantic_risk::classify_interaction_risk (POS: ARIA ref risk)
- toolkits.browser.tools._semantic_risk::classify_js_eval_risk (POS: JS eval risk)
- langgraph.types::interrupt (POS: LangGraph HITL interrupt mechanism)
- core.security.audit::record_decision (POS: Security decision audit trail)

[OUTPUT]
- enforce_semantic_interaction_guard: Gate click/dblclick on high-risk ARIA refs
- enforce_js_eval_guard: Gate mutating browser_manage evaluate expressions

[POS]
Single HITL approval path for browser_interact_tool, browser_execute_script
(session.interact), and browser_manage evaluate — prevents guard bypass.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.browser.tools._semantic_risk import (
    SemanticRiskLevel,
    classify_interaction_risk,
    classify_js_eval_risk,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.browser.session import BrowserSession
    from myrm_agent_harness.toolkits.browser.snapshot.aria_types import RefInfo

logger = logging.getLogger(__name__)


def _parse_interrupt_decision(user_response: object) -> bool:
    if isinstance(user_response, dict):
        return user_response.get("decision") == "approve"
    if isinstance(user_response, str):
        return user_response.lower() in ("approve", "allow", "yes", "y")
    return False


def _user_rejection_feedback(user_response: object) -> str:
    if isinstance(user_response, dict):
        return str(user_response.get("feedback", "") or "")
    return ""


async def _require_hitl_approval(
    *,
    session: BrowserSession,
    tool_name: str,
    reason: str,
    tool_input: dict[str, object],
    element: dict[str, str] | None = None,
) -> str | None:
    """Return a block message when the user rejects; None when approved."""
    from langgraph.types import interrupt

    from myrm_agent_harness.core.security.audit import record_decision

    page_url = ""
    try:
        page_url = session.page.url
    except Exception:
        logger.debug("Failed to retrieve page URL for semantic DOM guard")

    logger.warning(
        "[SEMANTIC_DOM_GUARD] High-risk action blocked for approval: tool=%s url=%s reason=%s",
        tool_name,
        page_url,
        reason,
    )

    record_decision(tool_name, "ASK", f"Semantic DOM guard: {reason}")

    hitl_payload: dict[str, object] = {
        "action_type": "high_risk_dom_action",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "reason": reason,
        "page_url": page_url,
    }
    if element is not None:
        hitl_payload["element"] = element

    user_response = interrupt(hitl_payload)

    if not _parse_interrupt_decision(user_response):
        record_decision(
            tool_name,
            "USER_REJECTED",
            f"User rejected high-risk DOM action: {reason}",
        )
        feedback = _user_rejection_feedback(user_response)
        return (
            f"[BLOCKED] User rejected this action: {reason}."
            + (f" Feedback: {feedback}" if feedback else "")
            + " Please find an alternative approach."
        )

    record_decision(
        tool_name,
        "USER_APPROVED",
        f"User approved high-risk DOM action: {reason}",
    )
    return None


async def enforce_semantic_interaction_guard(
    *,
    session: BrowserSession,
    tool_name: str,
    action: str,
    ref: str,
    ref_info: RefInfo | None,
    text: str = "",
) -> str | None:
    """Gate click/dblclick on high-risk ARIA refs. Returns block message or None."""
    if ref_info is None or not isinstance(getattr(ref_info, "name", None), str):
        return None

    verdict = classify_interaction_risk(action, ref_info)
    if verdict.level is not SemanticRiskLevel.HIGH:
        return None

    return await _require_hitl_approval(
        session=session,
        tool_name=tool_name,
        reason=verdict.reason,
        tool_input={"action": action, "ref": ref, "text": text},
        element={
            "role": ref_info.role,
            "name": ref_info.name,
            "ref": ref,
        },
    )


async def enforce_js_eval_guard(
    *,
    session: BrowserSession,
    tool_name: str,
    expression: str,
) -> str | None:
    """Gate mutating JS evaluate expressions. Returns block message or None."""
    verdict = classify_js_eval_risk(expression)
    if verdict.level is not SemanticRiskLevel.HIGH:
        return None

    return await _require_hitl_approval(
        session=session,
        tool_name=tool_name,
        reason=verdict.reason,
        tool_input={"action": "evaluate", "expression": expression},
    )
