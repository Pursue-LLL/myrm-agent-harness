"""LangChain tools for semantic desktop control (SDC).

[INPUT]
- desktop_session::DesktopSession (POS: semantic desktop orchestrator with @dref registry)
- types::ModifierKey, DesktopInteractAction, DesktopVisionAction, ScrollDirection (POS: shared computer_use types)
- element_ref.types::SnapshotScope (POS: snapshot scope enum)

[OUTPUT]
- create_desktop_tools(session) -> list[Tool]: 4 LangChain tools
  - desktop_inspect_tool
  - desktop_snapshot_tool
  - desktop_interact_tool
  - desktop_vision_tool

[POS]
LangChain tool surface for Semantic Desktop Control (SDC).
"""

from __future__ import annotations

from langchain.tools import tool
from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.computer_use.desktop_session import DesktopSession
from myrm_agent_harness.toolkits.computer_use.types import (
    DesktopInteractAction,
    DesktopVisionAction,
    ModifierKey,
    ScrollDirection,
)
from myrm_agent_harness.toolkits.element_ref.types import SnapshotScope


def create_desktop_tools(session: DesktopSession) -> list[object]:
    """Create 4 semantic desktop tools bound to *session*."""
    
    from myrm_agent_harness.toolkits.security.credential_vault import get_global_credential_vault
    vault = get_global_credential_vault()
    labels = vault.list_labels()
    labels_str = ", ".join([f"'{lbl}'" for lbl in labels]) if labels else "none available"

    class InspectInput(BaseModel):
        pass

    @tool("desktop_inspect_tool", args_schema=InspectInput)
    async def desktop_inspect() -> str:
        """Quickly inspect the foreground desktop app before taking a snapshot.

        Returns app/window metadata and a recommendation for desktop_snapshot_tool.
        """
        return await session.desktop_inspect()

    class SnapshotInput(BaseModel):
        scope: SnapshotScope = Field(
            default="foreground",
            description="Snapshot scope: 'foreground' (default), 'window_title', or 'full_screen'.",
        )
        window_title: str = Field(
            default="",
            description="Optional window title filter when scope='window_title'.",
        )
        include_screenshot: bool = Field(
            default=False,
            description="Include a screenshot image block alongside the AX tree.",
        )

    @tool("desktop_snapshot_tool", args_schema=SnapshotInput)
    async def desktop_snapshot(
        scope: SnapshotScope = "foreground",
        window_title: str = "",
        include_screenshot: bool = False,
    ) -> str | list[object]:
        """Capture the desktop accessibility tree with @dref element IDs.

        Workflow: desktop_inspect → desktop_snapshot → desktop_interact(ref=...).
        Use desktop_vision_tool only when the AX tree is empty.
        """
        result = await session.desktop_snapshot(
            scope=scope,
            window_title=window_title or None,
            include_screenshot=include_screenshot,
        )

        # Context-Aware Soft Routing: Check if the active window is a web browser
        warning_msg = ""
        try:
            is_browser = await session.backend.is_browser_active()
            if is_browser:
                warning_msg = (
                    "\n[SYSTEM HINT: The active window is a Web Browser. For interacting with web elements, "
                    "it is 10x faster, cheaper, and more reliable to use 'browser_snapshot' and 'browser_interact_tool'. "
                    "Only use desktop tools if you are dealing with native OS dialogs or browser extensions.]\n\n"
                )
        except Exception:
            pass

        if warning_msg:
            if isinstance(result, str):
                return warning_msg + result
            elif isinstance(result, list):
                # result is a list of content blocks (text + image)
                # We inject the warning into the first text block
                for block in result:
                    if isinstance(block, dict) and block.get("type") == "text":
                        block["text"] = warning_msg + str(block.get("text", ""))
                        break
                return result

        return result

    class InteractInput(BaseModel):
        ref: str = Field(description="Element @dref from desktop_snapshot (e.g. 'd3').")
        action: DesktopInteractAction = Field(
            description="One of: click, dblclick, fill, type, fill_credential, type_credential, press, hover, focus, scroll.",
        )
        text: str = Field(
            default="",
            description=f"Text for fill/type actions, or credential label for fill_credential/type_credential (available labels: {labels_str}).",
        )
        verify_goal: str | None = Field(
            default=None,
            description="Optional post-condition description (reserved; not yet enforced).",
        )
        modifiers: list[ModifierKey] | None = Field(
            default=None,
            description="Optional modifier keys for click-based actions.",
        )

    @tool("desktop_interact_tool", args_schema=InteractInput)
    async def desktop_interact(
        ref: str,
        action: DesktopInteractAction,
        text: str = "",
        verify_goal: str | None = None,
        modifiers: list[ModifierKey] | None = None,
    ) -> str | list[object]:
        """Perform an action on a desktop element identified by @dref."""
        return await session.desktop_interact(
            ref=ref,
            action=action,
            text=text,
            verify_goal=verify_goal,
            modifiers=modifiers,
        )

    class VisionInput(BaseModel):
        action: DesktopVisionAction = Field(
            description="Explicit visual fallback action using screenshot coordinates. Can also be type_credential.",
        )
        coordinate: list[int] | None = Field(
            default=None,
            description="[x, y] in screenshot image space.",
        )
        text: str | None = Field(
            default=None,
            description=f"Text for type/key actions, or credential label for type_credential (available labels: {labels_str}).",
        )
        scroll_direction: ScrollDirection | None = Field(default=None)
        scroll_amount: int = Field(default=3)
        start_coordinate: list[int] | None = Field(default=None)
        duration: float = Field(default=2.0)
        modifiers: list[ModifierKey] | None = Field(default=None)

    @tool("desktop_vision_tool", args_schema=VisionInput)
    async def desktop_vision(
        action: DesktopVisionAction,
        coordinate: list[int] | None = None,
        text: str | None = None,
        scroll_direction: ScrollDirection | None = None,
        scroll_amount: int = 3,
        start_coordinate: list[int] | None = None,
        duration: float = 2.0,
        modifiers: list[ModifierKey] | None = None,
    ) -> str | list[object]:
        """Explicit screenshot/coordinate fallback for canvas or AX-empty UI."""
        if action in ("capture", "screenshot"):
            return await session.desktop_vision_capture()
        return await session.desktop_vision_action(
            action=action,
            coordinate=coordinate,
            text=text,
            scroll_direction=scroll_direction,
            scroll_amount=scroll_amount,
            start_coordinate=start_coordinate,
            duration=duration,
            modifiers=modifiers,
        )

    return [desktop_inspect, desktop_snapshot, desktop_interact, desktop_vision]
