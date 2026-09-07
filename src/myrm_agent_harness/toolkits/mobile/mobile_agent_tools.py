"""LangChain Agent Tool Adapter for Mobile Android ADB Automation.

[INPUT]
- mobile_bridge::MobileBridge (POS: unified mobile bridge facade)
- types::MobileKey (POS: key definitions)

[OUTPUT]
- create_mobile_tools(bridge: MobileBridge | None = None) -> list[BaseTool]
  - mobile_screencap_tool
  - mobile_ui_dump_tool
  - mobile_input_tool
  - mobile_launch_app_tool

[POS]
LangChain tool surface for Android mobile device automation.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.mobile.mobile_bridge import (
    MobileBridge,
    create_mobile_bridge,
)
from myrm_agent_harness.toolkits.mobile.types import MobileKey


class ScreencapInput(BaseModel):
    serial: str = Field(
        default="",
        description="Optional target device serial number or IP:port. If omitted, uses the default connected device.",
    )
    include_base64: bool = Field(
        default=False,
        description="Whether to return full base64 encoded PNG data in output.",
    )


class UIDumpInput(BaseModel):
    serial: str = Field(
        default="",
        description="Optional target device serial or IP:port.",
    )
    clickable_only: bool = Field(
        default=True,
        description="If True, only returns clickable/interactive UI elements with their center coordinates.",
    )


class InputOperationInput(BaseModel):
    action: Literal["tap", "swipe", "type_text", "press_key"] = Field(
        description="Mobile touch or key action to execute.",
    )
    x: float = Field(
        default=0.0,
        description="X coordinate (pixel or normalized 0.0~1.0) for tap or swipe start.",
    )
    y: float = Field(
        default=0.0,
        description="Y coordinate (pixel or normalized 0.0~1.0) for tap or swipe start.",
    )
    end_x: float = Field(
        default=0.0,
        description="Target end X coordinate for swipe.",
    )
    end_y: float = Field(
        default=0.0,
        description="Target end Y coordinate for swipe.",
    )
    duration_ms: int = Field(
        default=300,
        description="Duration of swipe in milliseconds.",
    )
    text: str = Field(
        default="",
        description="Text to type (supports English, Chinese, and Unicode characters).",
    )
    key: str = Field(
        default="BACK",
        description="Hardware key name when action='press_key' (e.g. 'HOME', 'BACK', 'APP_SWITCH', 'POWER', 'ENTER').",
    )
    normalized: bool = Field(
        default=False,
        description="Set to True if x/y coordinates are normalized in 0.0~1.0 range.",
    )
    serial: str = Field(
        default="",
        description="Optional target device serial or IP:port.",
    )


class LaunchAppInput(BaseModel):
    app: str = Field(
        description="App package name (e.g. 'com.tencent.mm') or common alias ('wechat', 'settings', 'browser', 'camera').",
    )
    activity: str = Field(
        default="",
        description="Optional specific Activity class name to start.",
    )
    serial: str = Field(
        default="",
        description="Optional target device serial or IP:port.",
    )


def create_mobile_tools(bridge: MobileBridge | None = None) -> list[BaseTool]:
    """Create 4 LangChain tools for Android mobile automation."""
    active_bridge = bridge or create_mobile_bridge()

    @tool("mobile_screencap_tool", args_schema=ScreencapInput)
    async def mobile_screencap_tool(serial: str = "", include_base64: bool = False) -> str:
        """Capture the current screen of the connected Android mobile device."""
        target_serial = serial.strip() or None
        res = await active_bridge.inspector.screencap(serial=target_serial)
        if not res.image_bytes:
            return json.dumps({"error": "Failed to capture mobile screen. Ensure device is connected and awake."})

        payload: dict[str, Any] = {
            "success": True,
            "width": res.width,
            "height": res.height,
            "format": res.format,
            "size_bytes": len(res.image_bytes),
        }
        if include_base64:
            payload["base64_data"] = res.base64_data
        return json.dumps(payload, ensure_ascii=False)

    @tool("mobile_ui_dump_tool", args_schema=UIDumpInput)
    async def mobile_ui_dump_tool(serial: str = "", clickable_only: bool = True) -> str:
        """Extract current Android Accessibility XML hierarchy and calculate interactive element coordinates."""
        target_serial = serial.strip() or None
        res = await active_bridge.inspector.dump_ui_hierarchy(serial=target_serial)

        # Evaluate UI risk
        is_risky, reason = active_bridge.safety_guard.evaluate_ui_risk(
            res.top_package, res.clickable_elements, res.raw_xml
        )

        elements_data = [el.to_dict() for el in res.clickable_elements]
        payload: dict[str, Any] = {
            "top_package": res.top_package,
            "top_activity": res.top_activity,
            "is_sensitive_screen": is_risky,
            "safety_warning": reason,
            "interactive_elements_count": len(res.clickable_elements),
            "interactive_elements": elements_data,
        }
        return json.dumps(payload, ensure_ascii=False)

    @tool("mobile_input_tool", args_schema=InputOperationInput)
    async def mobile_input_tool(
        action: Literal["tap", "swipe", "type_text", "press_key"],
        x: float = 0.0,
        y: float = 0.0,
        end_x: float = 0.0,
        end_y: float = 0.0,
        duration_ms: int = 300,
        text: str = "",
        key: str = "BACK",
        normalized: bool = False,
        serial: str = "",
    ) -> str:
        """Send touch taps, swipe gestures, Unicode/Chinese text, or hardware keys to Android device."""
        target_serial = serial.strip() or None

        if action == "tap":
            res = await active_bridge.input_controller.tap(
                x=x, y=y, normalized=normalized, serial=target_serial
            )
        elif action == "swipe":
            res = await active_bridge.input_controller.swipe(
                start_x=x,
                start_y=y,
                end_x=end_x,
                end_y=end_y,
                duration_ms=duration_ms,
                normalized=normalized,
                serial=target_serial,
            )
        elif action == "type_text":
            res = await active_bridge.input_controller.type_text(
                text=text, serial=target_serial
            )
        elif action == "press_key":
            norm_key = key.upper().strip()
            res = await active_bridge.input_controller.press_key(
                key=norm_key,  # type: ignore[arg-type]
                serial=target_serial,
            )
        else:
            return json.dumps({"error": f"Unknown action: {action}"})

        return json.dumps(
            {
                "success": res.success,
                "action": res.action,
                "output": res.output,
                "error": res.error,
                "duration_ms": res.duration_ms,
            },
            ensure_ascii=False,
        )

    @tool("mobile_launch_app_tool", args_schema=LaunchAppInput)
    async def mobile_launch_app_tool(
        app: str,
        activity: str = "",
        serial: str = "",
    ) -> str:
        """Launch an Android application by package name or common alias (e.g. 'wechat', 'settings', 'browser')."""
        target_serial = serial.strip() or None
        target_act = activity.strip() or None
        res = await active_bridge.app_manager.launch_app(
            package_or_alias=app,
            activity=target_act,
            serial=target_serial,
        )
        return json.dumps(
            {
                "success": res.success,
                "action": res.action,
                "output": res.output,
                "error": res.error,
                "duration_ms": res.duration_ms,
            },
            ensure_ascii=False,
        )

    return [
        mobile_screencap_tool,
        mobile_ui_dump_tool,
        mobile_input_tool,
        mobile_launch_app_tool,
    ]
