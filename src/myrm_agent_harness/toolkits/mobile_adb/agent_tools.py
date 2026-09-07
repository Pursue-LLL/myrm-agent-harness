"""LangChain Tool adapter for Mobile ADB Automation.

[INPUT]
- myrm_agent_harness.toolkits.mobile_adb.session::MobileSession

[OUTPUT]
- create_mobile_adb_tools(session) -> list[BaseTool]:
  - mobile_snapshot_tool
  - mobile_interact_tool
  - mobile_device_manage_tool

[POS]
Exposes mobile wireless debugging tools to LangChain Agents.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from langchain.tools import tool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.mobile_adb.session import MobileSession


def create_mobile_adb_tools(session: MobileSession) -> list[object]:
    """Create 3 LangChain tools for Mobile ADB automation."""

    class MobileSnapshotInput(BaseModel):
        include_screenshot: bool = Field(
            default=False,
            description="Set to true when visual inspection or OCR is needed alongside the UI element tree.",
        )

    @tool("mobile_snapshot_tool", args_schema=MobileSnapshotInput)
    async def mobile_snapshot(include_screenshot: bool = False) -> str | list[object]:
        """Capture current Android device screen layout with semantic @m1..@mN references."""
        res = await session.snapshot(include_screenshot=include_screenshot)
        if not res.success:
            return f"Error taking mobile snapshot: {res.message} ({res.error})"

        if include_screenshot and res.screenshot_base64:
            return [
                {"type": "text", "text": res.message},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{res.screenshot_base64}"},
                },
            ]
        return res.message

    class MobileInteractInput(BaseModel):
        action: Literal[
            "tap",
            "type_text",
            "swipe",
            "launch_app",
            "press_back",
            "press_home",
            "press_recents",
        ] = Field(
            description="Action to perform on Android device: 'tap', 'type_text', 'swipe', 'launch_app', 'press_back', 'press_home', 'press_recents'."
        )
        ref_id: str = Field(
            default="",
            description="Target element ref ID from mobile_snapshot (e.g. '@m1', '@m2').",
        )
        x: int = Field(default=0, description="Target X coordinate (if not using ref_id).")
        y: int = Field(default=0, description="Target Y coordinate (if not using ref_id).")
        end_x: int = Field(default=0, description="End X coordinate for swipe gesture.")
        end_y: int = Field(default=0, description="End Y coordinate for swipe gesture.")
        text: str = Field(default="", description="Text to type into active input field.")
        package_name: str = Field(
            default="",
            description="Android package name to launch (e.g. 'com.tencent.mm', 'com.android.settings').",
        )

    @tool("mobile_interact_tool", args_schema=MobileInteractInput)
    async def mobile_interact(
        action: str,
        ref_id: str = "",
        x: int = 0,
        y: int = 0,
        end_x: int = 0,
        end_y: int = 0,
        text: str = "",
        package_name: str = "",
    ) -> str:
        """Perform touch, text typing, or navigation action on the connected Android device."""
        target_ref = ref_id if ref_id else None
        target_x = x if x > 0 else None
        target_y = y if y > 0 else None
        target_end_x = end_x if end_x > 0 else None
        target_end_y = end_y if end_y > 0 else None
        target_pkg = package_name if package_name else None
        target_text = text if text else None

        res = await session.interact(
            action=action,
            ref_id=target_ref,
            x=target_x,
            y=target_y,
            end_x=target_end_x,
            end_y=target_end_y,
            text=target_text,
            package_name=target_pkg,
        )
        if res.success:
            return f"Action '{action}' succeeded in {res.elapsed_ms:.1f}ms: {res.message}"
        return f"Action '{action}' failed: {res.message} ({res.error})"

    class MobileDeviceManageInput(BaseModel):
        command: Literal["list", "connect", "pair"] = Field(
            description="Device management command: 'list' (list devices), 'connect' (connect to IP:port), 'pair' (pair with code)."
        )
        host: str = Field(default="127.0.0.1", description="Target phone IP address.")
        port: int = Field(default=5555, description="Target phone port (connect or pairing port).")
        pairing_code: str = Field(default="", description="6-digit pairing code from Android Wireless Debugging.")

    @tool("mobile_device_manage_tool", args_schema=MobileDeviceManageInput)
    async def mobile_device_manage(
        command: str,
        host: str = "127.0.0.1",
        port: int = 5555,
        pairing_code: str = "",
    ) -> str:
        """Manage wireless ADB devices (pair, connect, list)."""
        if command == "list":
            devices = await session.list_devices()
            if not devices:
                return "No Android devices connected or discovered via ADB."
            lines = [f"Found {len(devices)} device(s):"]
            for d in devices:
                lines.append(f"- {d.device_id} ({d.model}) [{d.state}]")
            return "\n".join(lines)

        elif command == "pair":
            if not pairing_code:
                return "pairing_code is required to pair a new device."
            ok, msg = await session.pair_wireless_device(host, port, pairing_code)
            return msg if ok else f"Pairing failed: {msg}"

        elif command == "connect":
            ok, msg = await session.connect_device(host, port)
            return msg if ok else f"Connection failed: {msg}"

        return f"Unknown command: {command}"

    return [mobile_snapshot, mobile_interact, mobile_device_manage]
