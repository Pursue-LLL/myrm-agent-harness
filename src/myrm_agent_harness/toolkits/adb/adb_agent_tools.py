"""LangChain tool adapters for Mobile Wireless ADB automation.

[INPUT]
- engine::AdbBridgeEngine
- types::AdbTouchAction

[OUTPUT]
- create_mobile_adb_tools(engine) -> list[BaseTool]:
  - mobile_screencap_tool
  - mobile_ui_dump_tool
  - mobile_input_tool
  - mobile_launch_app_tool

[POS]
LangChain tool wrappers for Android Wireless ADB operations.
"""

from __future__ import annotations

from typing import Any
from langchain.tools import tool
from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.adb.engine import AdbBridgeEngine
from myrm_agent_harness.toolkits.adb.types import AdbTouchAction


def create_mobile_adb_tools(engine: AdbBridgeEngine) -> list[Any]:
    """Create LangChain-compatible tools for mobile ADB device control."""

    class ScreencapInput(BaseModel):
        include_base64: bool = Field(
            default=False,
            description="Whether to include full base64 bitmap in output (defaults to false to conserve tokens).",
        )

    @tool("mobile_screencap_tool", args_schema=ScreencapInput)
    async def mobile_screencap_tool(include_base64: bool = False) -> str:
        """Capture screenshot from connected mobile device. Returns screenshot status, package name, and optional base64 image."""
        snapshot = await engine.get_device_snapshot(include_screenshot=True)
        if not snapshot.screenshot_bytes:
            return f"Failed to capture mobile screenshot (State: {engine.state.value}). Ensure device is connected."

        res = f"Mobile screen captured successfully (Package: {snapshot.package_name}, Size: {len(snapshot.screenshot_bytes)} bytes)."
        if include_base64 and snapshot.screenshot_base64:
            res += f"\nImageBase64: {snapshot.screenshot_base64[:100]}...[truncated]"
        return res

    class UiDumpInput(BaseModel):
        filter_text: str = Field(
            default="",
            description="Optional keyword to filter element list (e.g. 'Login', 'Submit').",
        )

    @tool("mobile_ui_dump_tool", args_schema=UiDumpInput)
    async def mobile_ui_dump_tool(filter_text: str = "") -> str:
        """Extract semantic Accessibility UI element tree from connected mobile device, including @mref IDs and center coordinates."""
        snapshot = await engine.get_device_snapshot(include_screenshot=False)
        if not snapshot.elements:
            return f"No interactive UI elements found on screen (Package: {snapshot.package_name})."

        lines = [f"=== Mobile UI Tree ({snapshot.package_name}/{snapshot.activity_name}) ==="]
        for el in snapshot.elements:
            label = el.text or el.content_desc or el.resource_id
            if filter_text and filter_text.lower() not in label.lower():
                continue
            cx, cy = el.center
            flags = []
            if el.clickable:
                flags.append("clickable")
            if el.editable:
                flags.append("editable")
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            lines.append(f"{el.ref_id}: \"{label}\" at ({cx}, {cy}){flag_str}")

        return "\n".join(lines)

    class MobileInputSchema(BaseModel):
        action: AdbTouchAction = Field(
            description="Touch action: 'tap', 'swipe', 'text_input', or 'press_key'.",
        )
        x: int = Field(default=0, description="X coordinate for tap or swipe start.")
        y: int = Field(default=0, description="Y coordinate for tap or swipe start.")
        end_x: int = Field(default=0, description="End X coordinate for swipe.")
        end_y: int = Field(default=0, description="End Y coordinate for swipe.")
        text: str = Field(default="", description="Text to input when action='text_input'.")
        keycode: str = Field(default="", description="Hardware key code when action='press_key' (e.g. 'KEYCODE_HOME', 'KEYCODE_BACK').")

    @tool("mobile_input_tool", args_schema=MobileInputSchema)
    async def mobile_input_tool(
        action: AdbTouchAction,
        x: int = 0,
        y: int = 0,
        end_x: int = 0,
        end_y: int = 0,
        text: str = "",
        keycode: str = "",
    ) -> str:
        """Perform touch gestures (tap, swipe), text typing, or hardware key presses on connected mobile device."""
        res = await engine.send_input(
            action=action,
            x=x,
            y=y,
            end_x=end_x,
            end_y=end_y,
            text=text,
            keycode=keycode,
        )
        if not res.success:
            return f"Mobile action '{action.value}' failed: {res.error}"
        return f"Mobile action '{action.value}' executed successfully in {res.elapsed_ms}ms."

    class LaunchAppInput(BaseModel):
        package_name: str = Field(description="Android package name (e.g. 'com.tencent.mm', 'com.android.settings').")
        activity_name: str = Field(default="", description="Optional entry activity name.")

    @tool("mobile_launch_app_tool", args_schema=LaunchAppInput)
    async def mobile_launch_app_tool(package_name: str, activity_name: str = "") -> str:
        """Launch an Android application on the connected mobile device by package name."""
        res = await engine.launch_app(package_name, activity_name)
        if not res.success:
            return f"Failed to launch app '{package_name}': {res.error}"
        return f"App '{package_name}' launched successfully ({res.elapsed_ms}ms)."

    return [
        mobile_screencap_tool,
        mobile_ui_dump_tool,
        mobile_input_tool,
        mobile_launch_app_tool,
    ]
