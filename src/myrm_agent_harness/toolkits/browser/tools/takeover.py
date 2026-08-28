"""browser_ask_human tool — request user takeover of the browser session.

When the Agent encounters a situation it cannot handle autonomously (e.g. 2FA,
payment gateway, corporate SSO MFA push, proprietary CAPTCHA, handwriting
signature), it calls this tool to pause execution, notify the user via SSE
event, and wait for the user to complete the action in the browser.

The frontend receives a ``browser_takeover_requested`` event. Managed browser
sessions (sandbox VNC) auto-open the VNC panel; extension sessions show an
in-chat banner guiding the user to complete the step in Chrome.

[INPUT]
- langgraph.types::interrupt (POS: LangGraph HITL interrupt mechanism)
- utils.event_utils::dispatch_custom_event (POS: SSE event dispatch)
- ..session::BrowserSession (POS: active browser session)
- .common::mark_untrusted (POS: unified browser output security boundary; page/user-sourced URL, title, and user message are credential-redacted before reaching the LLM)

[OUTPUT]
- create_takeover_tool: Create browser_ask_human tool bound to session.

[POS]
Human-in-the-loop browser takeover tool. Agent-triggered, interrupt-based pause
that allows the user to directly operate the browser when automation is insufficient.
"""

from __future__ import annotations

import base64
import contextlib
import logging
import time
from typing import TYPE_CHECKING

from langchain.tools import tool
from pydantic import BaseModel, Field

from myrm_agent_harness.core.security.redact import redact_sensitive_text

from .common import mark_untrusted

if TYPE_CHECKING:
    from ..session import BrowserSession

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_S = 300.0


def create_takeover_tool(session: BrowserSession):
    """Create browser_ask_human tool bound to session."""

    class TakeoverInput(BaseModel):
        reason: str = Field(
            description="Clear explanation of WHY you need user takeover and WHAT the user should perform in the browser (e.g. 'Please enter the SMS verification code sent to your phone', 'Please complete payment authentication on the opened checkout page')."
        )

    @tool("browser_ask_human_tool", args_schema=TakeoverInput)
    async def browser_ask_human(reason: str) -> str:
        """Request the user to temporarily take over the browser and perform an action you cannot complete autonomously.

        Use this when encountering:
        - 2FA/MFA verification requiring user's phone, SMS, or authenticator app
        - Payment gateways requiring secure user credentials/passwords
        - Proprietary CAPTCHAs that automated solvers cannot solve
        - Digital handwriting/signature pads
        - Any interactive step requiring human authority or credentials

        Execution automatically pauses until the user completes the action in the browser.
        """
        from langgraph.types import interrupt

        from myrm_agent_harness.utils.event_utils import dispatch_custom_event

        page = getattr(session, "page", None)
        if page is None:
            try:
                if session._tab_controller.list_tabs():
                    page = session._tab_controller.get_active_page()
            except Exception:
                page = None
        if page is None or page.is_closed():
            try:
                await session.new_tab()
                page = session._tab_controller.get_active_page()
            except Exception:
                page = None
        if page is None or page.is_closed():
            return "Error: No active browser page. Navigate to a page first."

        is_managed = session.is_browser_managed()

        screenshot_b64: str | None = None
        try:
            screenshot_bytes = await page.screenshot(type="jpeg", quality=60)
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode("ascii")
        except Exception:
            logger.debug("Failed to capture screenshot for takeover request")

        current_url = ""
        with contextlib.suppress(Exception):
            current_url = page.url

        event_payload = {
            "reason": reason,
            "url": current_url,
            "screenshot_base64": screenshot_b64,
            "timeout_seconds": int(_DEFAULT_TIMEOUT_S),
            "is_managed": is_managed,
        }

        await dispatch_custom_event("browser_takeover_requested", event_payload)

        logger.info(
            "browser_ask_human: requesting user takeover — reason=%r url=%s",
            reason,
            redact_sensitive_text(current_url),
        )

        start = time.monotonic()

        hitl_payload = {
            "action_type": "browser_takeover",
            "tool_name": "browser_ask_human_tool",
            "reason": reason,
            "url": current_url,
            "screenshot_base64": screenshot_b64,
            "is_managed": is_managed,
        }

        user_response = interrupt(hitl_payload)

        elapsed_ms = (time.monotonic() - start) * 1000

        await dispatch_custom_event(
            "browser_takeover_completed",
            {
                "elapsed_ms": elapsed_ms,
                "url": current_url,
            },
        )

        post_url = ""
        with contextlib.suppress(Exception):
            post_url = page.url

        post_screenshot_desc = ""
        try:
            post_title = await page.title()
            post_screenshot_desc = f"Page title: {post_title}"
        except Exception:
            pass

        user_message = ""
        if isinstance(user_response, dict):
            user_message = user_response.get("message", "")
        elif isinstance(user_response, str):
            user_message = user_response

        logger.info(
            "browser_ask_human: user completed takeover (elapsed=%.0fms, url=%s -> %s)",
            elapsed_ms,
            redact_sensitive_text(current_url),
            redact_sensitive_text(post_url),
        )

        result_parts = [
            f"User completed the requested action (took {elapsed_ms / 1000:.1f}s).",
        ]
        if user_message:
            result_parts.append(f"User message: {user_message}")
        if post_url and post_url != current_url:
            result_parts.append(f"Page navigated to: {post_url}")
        if post_screenshot_desc:
            result_parts.append(post_screenshot_desc)
        result_parts.append("Please respond to the user with the outcome now.")

        # post_url / post_title / user_message are page-or-user-sourced and may
        # carry credentials (e.g. an OAuth callback URL with ?code=...). Route
        # through the unified browser output boundary so nothing reaches the LLM
        # context or persistent memory in plaintext.
        return mark_untrusted("\n".join(result_parts))

    from myrm_agent_harness.utils.tool_dynamic_hints import with_dynamic_hints

    return with_dynamic_hints(browser_ask_human, {})
