"""LangChain tools for semantic desktop control (SDC).

[INPUT]
- desktop_session::DesktopSession (POS: semantic desktop orchestrator with @dref registry)
- types::ModifierKey, DesktopInteractAction, DesktopVisionAction, ScrollDirection (POS: shared computer_use types)
- dref.types::SnapshotScope (POS: snapshot scope enum)

[OUTPUT]
- create_desktop_tools(session) -> list[Tool]: 3 LangChain tools
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
from myrm_agent_harness.toolkits.computer_use.dref.types import SnapshotScope
from myrm_agent_harness.toolkits.computer_use.types import (
    DesktopInteractAction,
    DesktopVisionAction,
    ModifierKey,
    ScrollDirection,
)


def create_desktop_tools(session: DesktopSession) -> list[object]:
    """Create 3 semantic desktop tools bound to *session*."""

    from myrm_agent_harness.core.security.credential_vault import (
        get_global_credential_vault,
    )

    vault = get_global_credential_vault()
    labels = vault.list_labels()
    labels_str = (
        ", ".join([f"'{lbl}'" for lbl in labels]) if labels else "none available"
    )

    class SnapshotInput(BaseModel):
        scope: SnapshotScope = Field(
            default="foreground",
            description="Snapshot scope: 'foreground' (default, active app window) or 'target' (a specific app by name).",
        )
        app_name: str = Field(
            default="",
            description="Target app name (e.g. 'Mail', 'Excel') when scope='target'. Captures that app's main window without changing the foreground.",
        )
        include_screenshot: bool = Field(
            default=False,
            description="Set to true only when visual layout, icons, canvas areas, or colors must be inspected alongside the AX tree.",
        )
        query: str = Field(
            default="",
            description="Optional keyword query to filter and prioritize matching elements in the accessibility tree, bypassing hard element count limits.",
        )
        role: str = Field(
            default="",
            description="Optional role filter (e.g. 'button', 'text field', 'menu item') to narrow down accessibility elements.",
        )
        wait_seconds: float = Field(
            default=0.0,
            description="Optional delay in seconds (0.0-10.0) before taking the snapshot to wait for UI rendering or animations.",
        )

    @tool("desktop_snapshot_tool", args_schema=SnapshotInput)
    async def desktop_snapshot(
        scope: SnapshotScope = "foreground",
        app_name: str = "",
        include_screenshot: bool = False,
        query: str = "",
        role: str = "",
        wait_seconds: float = 0.0,
    ) -> str | list[object]:
        """Capture the active desktop accessibility (AX) tree with @dref element IDs.

        Required workflow: Always call desktop_snapshot_tool first to obtain current @dref element references, then call desktop_interact_tool(ref=@dref, action=...) to act on elements.
        Use scope='foreground' (default) for active window, or scope='target' with app_name to inspect background apps. Use query/role to filter elements and wait_seconds for animations.
        """
        result = await session.desktop_snapshot(
            scope=scope,
            app_name=app_name or None,
            include_screenshot=include_screenshot,
            query=query or None,
            role=role or None,
            wait_seconds=wait_seconds,
        )

        warning_msg = ""
        try:
            is_browser = await session._backend.is_browser_active()
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
            if isinstance(result, list):
                for block in result:
                    if isinstance(block, dict) and block.get("type") == "text":
                        block["text"] = warning_msg + str(block.get("text", ""))
                        break
                return result

        return result

    class InteractInput(BaseModel):
        ref: str = Field(
            description="Element @dref obtained from the latest desktop_snapshot_tool call (e.g. 'd3'). Do not guess refs.",
        )
        action: DesktopInteractAction = Field(
            description=(
                "Action to perform: 'click', 'dblclick', 'set_value' (atomic text replace, recommended for text inputs), "
                "'fill' (focus and fill), 'type' (keyboard keystroke simulation), 'fill_credential' (inject vault credential), "
                "'press' (activate/AXPress the @dref control — same family as click, not a keyboard key name), "
                "'hover', 'focus', 'scroll', 'toggle'/'check'/'uncheck', 'expand'/'collapse', 'invoke'."
            ),
        )
        text: str = Field(
            default="",
            description=(
                f"Text for set_value/fill/type, or credential label for fill_credential "
                f"(available: {labels_str}; append '-totp' for TOTP token). "
                "Unused for press/click/hover/focus (those activate the @dref element). "
                "For Return/Escape/hotkeys use desktop_vision_tool action=key — never pass printable operators "
                "('*', '/', '+', '-', '%', '=') as key names; type them or click the calculator/@dref button."
            ),
        )
        modifiers: list[ModifierKey] | None = Field(
            default=None,
            description="Optional modifier keys for click-based actions (e.g. ['shift'], ['ctrl']).",
        )
        wait_seconds: float = Field(
            default=0.0,
            description="Optional delay in seconds (0.0-10.0) after performing the action before capturing the follow-up snapshot (useful for waiting for modal dialogs, exports, or network operations to settle).",
        )

    @tool("desktop_interact_tool", args_schema=InteractInput)
    async def desktop_interact(
        ref: str,
        action: DesktopInteractAction,
        text: str = "",
        modifiers: list[ModifierKey] | None = None,
        wait_seconds: float = 0.0,
    ) -> str | list[object]:
        """Perform a semantic action on a desktop element identified by @dref from desktop_snapshot_tool.

        Always call desktop_snapshot_tool first to obtain current @drefs, then call this tool with the valid ref.
        """
        return await session.desktop_interact(
            ref=ref,
            action=action,
            text=text,
            modifiers=modifiers,
            wait_seconds=wait_seconds,
        )

    class VisionInput(BaseModel):
        action: DesktopVisionAction = Field(
            description="Visual action: 'screenshot'/'capture' (grab screen image), 'left_click', 'right_click', 'double_click', 'triple_click', 'type' (type text), 'key' (press key/hotkey), 'scroll', 'drag', 'mouse_move', 'wait'.",
        )
        coordinate: list[int] | None = Field(
            default=None,
            description="[x, y] in screenshot image space for click/move actions.",
        )
        text: str | None = Field(
            default=None,
            description=(
                "Text to type for 'type' action, or key combination for 'key' action "
                "(e.g. 'Return', 'Escape', 'ctrl+c'). Do not pass printable operators "
                "('*', '/', '+', '-', '%', '=') as key names — use type or click calculator/@dref via desktop_interact_tool."
            ),
        )
        scroll_direction: ScrollDirection | None = Field(
            default=None,
            description="Scroll direction ('up', 'down', 'left', 'right') for 'scroll' action.",
        )
        scroll_amount: int = Field(default=3, description="Number of scroll steps/units.")
        start_coordinate: list[int] | None = Field(
            default=None,
            description="[x, y] start coordinate for 'drag' action.",
        )
        duration: float = Field(
            default=2.0,
            description="Duration in seconds for smooth actions like drag or wait.",
        )
        modifiers: list[ModifierKey] | None = Field(
            default=None,
            description="Optional modifier keys (e.g. ['shift'], ['ctrl']).",
        )

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
        """Explicit screenshot/coordinate fallback for canvas areas, games, or windows with empty AX trees.

        Workflow: 1) Call action='screenshot' (or 'capture') to get current screen image and coordinates; 2) Call with coordinate action ('left_click', 'type', etc.) using [x, y] in screenshot image space.
        """
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

    return [desktop_snapshot, desktop_interact, desktop_vision]
