"""LangChain tool interface for Mobile Device (Android Wireless ADB) automation.

[INPUT]
- driver::AndroidAdbBackend (POS: mobile backend driver)

[OUTPUT]
- create_mobile_tools(backend) -> list[Tool]:
  - mobile_snapshot_tool
  - mobile_interact_tool
  - mobile_launch_tool

[POS]
Semantic mobile automation surface for agent execution.
"""

from __future__ import annotations

from typing import Literal
from langchain.tools import tool
from pydantic import BaseModel, Field

from .driver import AndroidAdbBackend


def create_mobile_tools(backend: AndroidAdbBackend) -> list[object]:
    """Create semantic mobile device control tools bound to *backend*."""

    class MobileSnapshotInput(BaseModel):
        include_screenshot: bool = Field(
            default=False,
            description="Set to true when visual inspection of colors, images, or layout is required alongside the UI tree.",
        )
        format: Literal["WEBP", "JPEG"] = Field(
            default="WEBP",
            description="Compressed screenshot format.",
        )

    @tool("mobile_snapshot_tool", args_schema=MobileSnapshotInput)
    async def mobile_snapshot_tool(
        include_screenshot: bool = False,
        format: Literal["WEBP", "JPEG"] = "WEBP",
    ) -> str | list[object]:
        """Capture the active Android screen's interactive accessibility hierarchy with @m{index} references.

        Always call mobile_snapshot_tool first to see actionable UI elements (buttons, inputs, lists) before interacting.
        """
        _, markdown_summary = await backend.ui_snapshot()
        if not include_screenshot:
            return markdown_summary

        screenshot_bytes = await backend.screenshot(format=format)
        import base64
        b64_img = base64.b64encode(screenshot_bytes).decode("ascii")
        return [
            {"type": "text", "text": markdown_summary},
            {"type": "image_url", "image_url": {"url": f"data:image/{format.lower()};base64,{b64_img}"}},
        ]

    class MobileInteractInput(BaseModel):
        action: Literal["tap_ref", "tap_coord", "swipe", "type_text", "key"] = Field(
            description="Mobile interaction action to perform.",
        )
        ref: str = Field(
            default="",
            description="Semantic element reference (e.g. '@m1', '@m5') from the last snapshot. Used when action='tap_ref'.",
        )
        x: int = Field(default=0, description="X coordinate on screen. Used when action='tap_coord'.")
        y: int = Field(default=0, description="Y coordinate on screen. Used when action='tap_coord'.")
        start_x: int = Field(default=0, description="Swipe start X coordinate.")
        start_y: int = Field(default=0, description="Swipe start Y coordinate.")
        end_x: int = Field(default=0, description="Swipe end X coordinate.")
        end_y: int = Field(default=0, description="Swipe end Y coordinate.")
        text: str = Field(default="", description="Text to type when action='type_text'. Supports Chinese/English/Emoji.")
        key_name: str = Field(
            default="",
            description="Key to press when action='key' (e.g. 'back', 'home', 'enter', 'power').",
        )

    @tool("mobile_interact_tool", args_schema=MobileInteractInput)
    async def mobile_interact_tool(
        action: Literal["tap_ref", "tap_coord", "swipe", "type_text", "key"],
        ref: str = "",
        x: int = 0,
        y: int = 0,
        start_x: int = 0,
        start_y: int = 0,
        end_x: int = 0,
        end_y: int = 0,
        text: str = "",
        key_name: str = "",
    ) -> str:
        """Perform touch gestures, typing, or hardware key presses on the connected Android phone."""
        if action == "tap_ref":
            if not ref.startswith("@m"):
                return "Error: ref must be formatted as '@m1', '@m2', etc."
            try:
                idx = int(ref[2:])
                res = await backend.tap_node(idx)
                return res.message
            except ValueError:
                return f"Error: Invalid ref index '{ref}'."

        if action == "tap_coord":
            res = await backend.tap(x, y)
            return res.message

        if action == "swipe":
            res = await backend.swipe(start_x, start_y, end_x, end_y)
            return res.message

        if action == "type_text":
            res = await backend.type_text(text)
            return res.message

        if action == "key":
            res = await backend.key(key_name)
            return res.message

        return f"Unknown action: {action}"

    class MobileLaunchInput(BaseModel):
        app: str = Field(
            description="App package name or popular alias (e.g. 'wechat', 'dingtalk', 'settings', 'chrome').",
        )

    @tool("mobile_launch_tool", args_schema=MobileLaunchInput)
    async def mobile_launch_tool(app: str) -> str:
        """Launch an Android application by package name or alias."""
        res = await backend.launch_app(app)
        return res.message

    return [mobile_snapshot_tool, mobile_interact_tool, mobile_launch_tool]
