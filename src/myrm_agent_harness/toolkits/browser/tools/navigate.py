"""browser_navigate tool for URL navigation.

[INPUT]
- utils.errors::ToolError (POS: Storage quota related errors.)

[OUTPUT]
- create_navigate_tool: Create browser_navigate tool bound to session.

[POS]
browser_navigate tool for URL navigation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain.tools import tool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from ..session import BrowserSession


def create_navigate_tool(session: BrowserSession):
    """Create browser_navigate tool bound to session."""

    class NavigateInput(BaseModel):
        url: str = Field(description="Target URL to navigate to")
        verify_goal: str | None = Field(
            default=None,
            description="Optional. A natural language description of what you expect to see after navigation completes (e.g., 'Google homepage is fully loaded', 'Login form is visible'). If provided, the tool will take screenshots before and after, and use a Vision LLM to verify if the goal was met, returning the visual feedback directly to you.",
        )

    from myrm_agent_harness.utils.tool_dynamic_hints import with_dynamic_hints

    @tool("browser_navigate_tool", args_schema=NavigateInput)
    async def browser_navigate(url: str, verify_goal: str | None = None) -> str:
        """Open a URL in the browser. Returns page title, final URL, and status code."""
        # URL data exfiltration detection (P0 Critical Security)
        import logging

        from myrm_agent_harness.utils.errors import ToolError
        from myrm_agent_harness.utils.url_utils import check_url_exfiltration, sanitize_url_for_error

        warnings = check_url_exfiltration(url, allow_private_networks=True)
        if warnings:
            logger = logging.getLogger(__name__)
            safe_url = sanitize_url_for_error(url)
            logger.warning(f" Data exfiltration detected in browser_navigate: {safe_url}")
            for warning in warnings:
                logger.warning(f"  - {warning}")
            raise ToolError(
                f"Navigation blocked (data exfiltration): {'; '.join(warnings)} — URL: {safe_url}",
                user_hint="The URL contains sensitive data (API keys, file paths, or credentials). Remove sensitive data from the URL.",
            )

        return await session.navigate(url, verify_goal=verify_goal)

    return with_dynamic_hints(
        browser_navigate,
        {"web_search_tool": "For simple information retrieval, prefer web_search_tool (faster, cheaper)."},
    )
