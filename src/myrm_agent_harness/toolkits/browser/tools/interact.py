"""browser_interact tool for element interactions.

[INPUT]
- (none)

[OUTPUT]
- create_interact_tool: Create browser_interact tool bound to session.

[POS]
browser_interact tool for element interactions.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from langchain.tools import tool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from ..session import BrowserSession


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

        result = await session.interact(action, ref, text, verify_goal=verify_goal)

        if action in ("click", "dblclick") and session.download_enabled:
            await asyncio.sleep(0.5)
            if len(session.list_downloads()) > count_before:
                latest = session.last_download
                if latest:
                    result = f"{result}\nFile downloaded: {latest.file_name} ({latest.file_size} bytes)"

        return result

    return browser_interact
