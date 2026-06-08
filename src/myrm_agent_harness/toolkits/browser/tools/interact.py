"""browser_interact tool for element interactions.

[INPUT]
- toolkits.browser.tools._semantic_risk::classify_interaction_risk (POS: Pure function semantic DOM risk classification)
- core.security.audit::record_decision (POS: Security decision audit trail)
- langgraph.types::interrupt (POS: LangGraph HITL interrupt mechanism)

[OUTPUT]
- create_interact_tool: Create browser_interact tool bound to session.

[POS]
browser_interact tool for element interactions. Includes semantic DOM risk check
that gates destructive/financial/admin click actions via HITL approval.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from langchain.tools import tool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from ..session import BrowserSession

logger = logging.getLogger(__name__)


def create_interact_tool(session: BrowserSession):
    """Create browser_interact tool bound to session."""

    from myrm_agent_harness.toolkits.security.credential_vault import get_global_credential_vault

    vault = get_global_credential_vault()
    labels = vault.list_labels()
    labels_str = ", ".join([f"'{lbl}'" for lbl in labels]) if labels else "none available"

    class InteractInput(BaseModel):
        action: str = Field(
            description="One of: click, dblclick, type (append keystrokes), fill (clear then set value), "
            "fill_credential (securely fill password/totp), "
            "press, hover, focus, select, scroll, upload_file, drag, "
            "check (idempotent checkbox on), uncheck (idempotent checkbox off)",
        )
        ref: str = Field(
            description="Element ref from browser_snapshot (e.g. 'e0', 'e3', 'f1_e2' for iframe elements)",
        )
        text: str = Field(
            default="",
            description="Text for type/fill, key combo for press (e.g. 'Enter', 'Control+a'), "
            f"credential label for fill_credential (available labels: {labels_str}), "
            "option value for select, signed scroll delta in pixels (positive=down, negative=up), "
            "file path for upload_file, target ref for drag. Omit for click/dblclick/hover/focus/check/uncheck.",
        )
        verify_goal: str | None = Field(
            default=None,
            description="Optional. A natural language description of what you expect to see after this action (e.g., 'Flight list is visible', 'Error message disappeared'). If provided, the tool will take screenshots before and after, and use a Vision LLM to verify if the goal was met, returning the visual feedback directly to you.",
        )

    @tool("browser_interact_tool", args_schema=InteractInput)
    async def browser_interact(action: str, ref: str, text: str = "", verify_goal: str | None = None) -> str:
        """Perform an action on a page element identified by its ref ID.

        Workflow: browser_snapshot -> pick ref -> browser_interact.
        Works across iframes (refs like 'f1_e2' target iframe elements).
        If click triggers a file download, it's auto-captured; use list_downloads to check.
        Use verify_goal to automatically verify the visual result of your action without needing to call a separate vision tool.
        """
        count_before = len(session.list_downloads())

        ref_info = session.get_ref_info(ref)
        if ref_info is not None and isinstance(getattr(ref_info, "name", None), str):
            from myrm_agent_harness.toolkits.browser.tools._semantic_risk import (
                SemanticRiskLevel,
                classify_interaction_risk,
            )

            verdict = classify_interaction_risk(action, ref_info)
            if verdict.level is SemanticRiskLevel.HIGH:
                from langgraph.types import interrupt

                from myrm_agent_harness.core.security.audit import record_decision

                page_url = ""
                try:
                    page_url = session.page.url
                except Exception:
                    logger.debug("Failed to retrieve page URL for semantic DOM guard")

                logger.warning(
                    "[SEMANTIC_DOM_GUARD] High-risk interaction blocked for approval: "
                    "action=%s ref=%s role=%s name=%r url=%s",
                    action, ref, ref_info.role, ref_info.name, page_url,
                )

                record_decision(
                    "browser_interact_tool",
                    "ASK",
                    f"Semantic DOM guard: {verdict.reason}",
                )

                hitl_payload = {
                    "action_type": "high_risk_dom_action",
                    "tool_name": "browser_interact_tool",
                    "tool_input": {"action": action, "ref": ref, "text": text},
                    "reason": verdict.reason,
                    "element": {
                        "role": ref_info.role,
                        "name": ref_info.name,
                        "ref": ref,
                    },
                    "page_url": page_url,
                }

                user_response = interrupt(hitl_payload)

                approved = False
                if isinstance(user_response, dict):
                    approved = user_response.get("decision") == "approve"
                elif isinstance(user_response, str):
                    approved = user_response.lower() in ("approve", "allow", "yes", "y")

                if not approved:
                    record_decision(
                        "browser_interact_tool",
                        "USER_REJECTED",
                        f"User rejected high-risk DOM action: {verdict.reason}",
                    )
                    feedback = ""
                    if isinstance(user_response, dict):
                        feedback = user_response.get("feedback", "")
                    return (
                        f"[BLOCKED] User rejected this action: {verdict.reason}."
                        + (f" Feedback: {feedback}" if feedback else "")
                        + " Please find an alternative approach."
                    )

                record_decision(
                    "browser_interact_tool",
                    "USER_APPROVED",
                    f"User approved high-risk DOM action: {verdict.reason}",
                )

        result = await session.interact(action, ref, text, verify_goal=verify_goal)

        if action in ("click", "dblclick") and session.download_enabled:
            await asyncio.sleep(0.5)
            if len(session.list_downloads()) > count_before:
                latest = session.last_download
                if latest:
                    result = f"{result}\nFile downloaded: {latest.file_name} ({latest.file_size} bytes)"

        return result

    return browser_interact
