"""LangChain tool surface for Mobile Wireless ADB automation.

[INPUT]
- session::MobileSession (POS: mobile session orchestrator)
- types::MobileActionType (POS: action types)

[OUTPUT]
- create_mobile_adb_tools(session) -> list[BaseTool]: 3 LangChain tools
  - mobile_snapshot_tool
  - mobile_interact_tool
  - mobile_global_tool

[POS]
LangChain tool wrappers exposing semantic mobile control to AI Agent runtime.
"""

from __future__ import annotations

import base64
from typing import Any

from langchain.tools import tool
from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.mobile_adb.session import MobileSession


def create_mobile_adb_tools(session: MobileSession) -> list[object]:
    """Create 3 LangChain tools bound to the active *session*."""

    class MobileSnapshotInput(BaseModel):
        target: str = Field(
            default="",
            description="Optional target device IP:port (e.g. '192.168.1.50:5555'). Defaults to active connected device.",
        )
        include_screenshot: bool = Field(
            default=False,
            description="Whether to capture and return a base64 screenshot along with the @mref UI element tree.",
        )

    @tool("mobile_snapshot_tool", args_schema=MobileSnapshotInput)
    async def mobile_snapshot_tool(
        target: str = "",
        include_screenshot: bool = False,
    ) -> dict[str, Any]:
        """Capture the current Android screen accessibility hierarchy and @mref element index.

        Use this tool to inspect what is currently visible on the mobile phone screen before taking actions.
        Returns a list of UI elements with @mref IDs, text, descriptions, and clickable status.
        """
        try:
            state, screenshot_bytes = await session.snapshot(
                target=target, include_screenshot=include_screenshot
            )
            element_summaries = [elem.to_summary() for elem in state.elements]
            res: dict[str, Any] = {
                "success": True,
                "device": state.device_id,
                "current_package": state.current_package,
                "current_activity": state.current_activity,
                "screen_size": f"{state.screen_width}x{state.screen_height}",
                "element_count": len(state.elements),
                "elements": element_summaries,
            }
            if screenshot_bytes:
                b64_img = base64.b64encode(screenshot_bytes).decode("ascii")
                res["screenshot_base64"] = b64_img
            return res
        except Exception as e:
            return {"success": False, "error": str(e)}

    class MobileInteractInput(BaseModel):
        ref: str = Field(
            description="The target element reference ID (e.g. '@mref_1') obtained from mobile_snapshot_tool.",
        )
        action: str = Field(
            description="Action to perform: 'click', 'long_press', 'input_text', or 'clear_text'.",
        )
        text: str = Field(
            default="",
            description="Text to type into the element when action='input_text'.",
        )
        target: str = Field(
            default="",
            description="Optional target device IP:port. Defaults to active connected device.",
        )

    @tool("mobile_interact_tool", args_schema=MobileInteractInput)
    async def mobile_interact_tool(
        ref: str,
        action: str,
        text: str = "",
        target: str = "",
    ) -> dict[str, Any]:
        """Perform semantic action on a UI element using its @mref ID.

        Supports clicking buttons, typing into input fields, and clearing text fields.
        Always run mobile_snapshot_tool first to obtain valid @mref IDs.
        """
        try:
            result = await session.interact(
                ref=ref,
                action=action,
                text=text,
                target=target,
            )
            return {
                "success": result.success,
                "action": result.action,
                "message": result.message,
                "error": result.error,
                "data": result.data,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    class MobileGlobalInput(BaseModel):
        action: str = Field(
            description="Global action: 'back' (press Back), 'home' (press Home), 'launch_app' (open app by package), 'stop_app' (force stop).",
        )
        param: str = Field(
            default="",
            description="Package name parameter when action is 'launch_app' or 'stop_app' (e.g. 'com.tencent.mm').",
        )
        target: str = Field(
            default="",
            description="Optional target device IP:port.",
        )

    @tool("mobile_global_tool", args_schema=MobileGlobalInput)
    async def mobile_global_tool(
        action: str,
        param: str = "",
        target: str = "",
    ) -> dict[str, Any]:
        """Execute device-level global navigation or application lifecycle actions on Android.

        Use this to press Home, press Back, or open/close apps by package name.
        """
        try:
            result = await session.global_action(
                action=action,
                param=param,
                target=target,
            )
            return {
                "success": result.success,
                "action": result.action,
                "message": result.message,
                "error": result.error,
                "data": result.data,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    return [mobile_snapshot_tool, mobile_interact_tool, mobile_global_tool]
