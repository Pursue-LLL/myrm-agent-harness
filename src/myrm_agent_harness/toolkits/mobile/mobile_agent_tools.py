"""LangChain tool surface for Mobile Wireless ADB automation.

[INPUT]
- mobile_bridge::MobileBridge (POS: unified mobile automation facade)
- types::KeyCode, TouchAction (POS: mobile types)

[OUTPUT]
- create_mobile_tools(bridge) -> list[BaseTool]: 5 LangChain agent tools
  - mobile_device_tool
  - mobile_snapshot_tool
  - mobile_touch_tool
  - mobile_input_tool
  - mobile_app_tool

[POS]
LangChain adapter layer in toolkits/mobile.
"""

from __future__ import annotations

import json
from typing import Any

from langchain.tools import tool
from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.mobile.mobile_bridge import MobileBridge
from myrm_agent_harness.toolkits.mobile.types import KeyCode


def create_mobile_tools(bridge: MobileBridge | None = None) -> list[object]:
    """Create 5 LangChain mobile tools bound to *bridge*."""
    active_bridge = bridge or MobileBridge()

    # ---------------- 1. Device Management Tool ----------------
    class DeviceInput(BaseModel):
        action: str = Field(
            description="Action to perform: 'list' (discover devices), 'connect' (connect IP:port), 'pair' (pair Android 11+ with code), 'disconnect' (disconnect device).",
        )
        host: str = Field(default="", description="IP address or hostname of the Android device.")
        port: int = Field(default=5555, description="Port number (default 5555 for connect, pairing port for pair).")
        pairing_code: str = Field(default="", description="6-digit Wi-Fi pairing code when action='pair'.")

    @tool("mobile_device_tool", args_schema=DeviceInput)
    async def mobile_device_tool(
        action: str,
        host: str = "",
        port: int = 5555,
        pairing_code: str = "",
    ) -> str:
        """Discover, pair, or connect to Android mobile devices over Wireless ADB or USB."""
        action_clean = action.strip().lower()
        if action_clean == "list":
            devices = await active_bridge.list_devices()
            if not devices:
                return "No Android devices found. Make sure Wireless Debugging or USB debugging is enabled."
            out = ["Connected / Available Android Devices:"]
            for d in devices:
                mode_str = "Wireless" if d.is_wireless else "USB"
                out.append(f"- [{d.state.value.upper()}] {d.serial} ({d.model}, {mode_str})")
            return "\n".join(out)

        elif action_clean == "pair":
            if not host or not pairing_code:
                return "Error: 'host' and 'pairing_code' are required for action='pair'."
            res = await active_bridge.pair_device(host, port, pairing_code)
            return f"Pairing result: {res.message}"

        elif action_clean == "connect":
            if not host:
                return "Error: 'host' is required for action='connect'."
            res = await active_bridge.connect_device(host, port)
            return f"Connection result: {res.message}"

        elif action_clean == "disconnect":
            target = f"{host}:{port}" if host else ""
            res = await active_bridge.disconnect_device(target)
            return f"Disconnect result: {res.message}"

        return f"Unknown device action: '{action}'."

    # ---------------- 2. Snapshot & Inspection Tool ----------------
    class SnapshotInput(BaseModel):
        include_screenshot: bool = Field(
            default=False,
            description="Set to true to capture screen bitmap alongside hierarchy XML tree.",
        )
        query: str = Field(
            default="",
            description="Optional search text to filter matching UI elements on screen.",
        )
        compressed: bool = Field(
            default=True,
            description="Use compressed hierarchy dump to optimize speed and token efficiency.",
        )

    @tool("mobile_snapshot_tool", args_schema=SnapshotInput)
    async def mobile_snapshot_tool(
        include_screenshot: bool = False,
        query: str = "",
        compressed: bool = True,
    ) -> str:
        """Inspect the current Android mobile screen, dumping the accessibility tree and interactive elements."""
        try:
            hierarchy = await active_bridge.dump_hierarchy(compressed=compressed)
            verdict = active_bridge.evaluate_hierarchy(hierarchy)

            out = [
                f"Screen Resolution: {hierarchy.screen_width}x{hierarchy.screen_height}",
                f"Safety Status: {verdict.risk_level} ({verdict.reason})",
            ]

            if query:
                matches = hierarchy.find_by_text(query)
                out.append(f"\nMatching Elements for '{query}' ({len(matches)} found):")
                for node in matches[:20]:
                    nc = node.bounds.to_normalized_center(hierarchy.screen_width, hierarchy.screen_height)
                    out.append(
                        f"- [{node.class_name.split('.')[-1]}] '{node.text or node.content_desc}' id={node.resource_id} bounds={node.bounds.left},{node.bounds.top}~{node.bounds.right},{node.bounds.bottom} center=({node.bounds.center.x},{node.bounds.center.y}) norm_center=({nc[0]},{nc[1]})"
                    )
            else:
                interactives = hierarchy.find_all_interactive()
                out.append(f"\nInteractive Elements ({len(interactives)} found):")
                for node in interactives[:30]:
                    label = node.text or node.content_desc or node.resource_id.split("/")[-1] or "Element"
                    nc = node.bounds.to_normalized_center(hierarchy.screen_width, hierarchy.screen_height)
                    out.append(
                        f"- [{node.class_name.split('.')[-1]}] '{label}' bounds={node.bounds.left},{node.bounds.top}~{node.bounds.right},{node.bounds.bottom} norm_center=({nc[0]},{nc[1]})"
                    )

            if include_screenshot:
                screencap = await active_bridge.screencap()
                out.append(f"\n[Screenshot captured: {screencap.width}x{screencap.height} PNG, base64_len={len(screencap.base64_data)}]")

            return "\n".join(out)
        except Exception as e:
            return f"Mobile snapshot error: {e}"

    # ---------------- 3. Touch & Gesture Tool ----------------
    class TouchInput(BaseModel):
        action: str = Field(
            description="Touch action: 'tap' (tap single coordinate), 'swipe' (swipe from x1,y1 to x2,y2).",
        )
        x: float = Field(default=0.0, description="X coordinate (pixel integer or 0.0-1.0 normalized float).")
        y: float = Field(default=0.0, description="Y coordinate (pixel integer or 0.0-1.0 normalized float).")
        x2: float = Field(default=0.0, description="End X coordinate for swipe.")
        y2: float = Field(default=0.0, description="End Y coordinate for swipe.")
        duration_ms: int = Field(default=300, description="Swipe duration in milliseconds.")
        normalized: bool = Field(
            default=False,
            description="True if coordinates are given as normalized floats (0.0 - 1.0).",
        )

    @tool("mobile_touch_tool", args_schema=TouchInput)
    async def mobile_touch_tool(
        action: str,
        x: float = 0.0,
        y: float = 0.0,
        x2: float = 0.0,
        y2: float = 0.0,
        duration_ms: int = 300,
        normalized: bool = False,
    ) -> str:
        """Perform touch actions (tap or swipe) on the Android screen."""
        action_clean = action.strip().lower()
        if action_clean == "tap":
            res = await active_bridge.tap(x=x, y=y, normalized=normalized)
            return res.message
        elif action_clean == "swipe":
            res = await active_bridge.swipe(
                x1=x,
                y1=y,
                x2=x2,
                y2=y2,
                duration_ms=duration_ms,
                normalized=normalized,
            )
            return res.message
        return f"Unknown touch action: '{action}'. Use 'tap' or 'swipe'."

    # ---------------- 4. Text & Key Input Tool ----------------
    class InputParams(BaseModel):
        action: str = Field(
            description="Input action: 'type' (enter text including Chinese/Unicode), 'key' (press hardware key: home, back, enter, power, app_switch).",
        )
        text: str = Field(default="", description="Text to type into active input field.")
        key_name: str = Field(
            default="",
            description="Key name when action='key' (e.g. 'home', 'back', 'enter', 'app_switch', 'volume_up', 'volume_down').",
        )

    @tool("mobile_input_tool", args_schema=InputParams)
    async def mobile_input_tool(
        action: str,
        text: str = "",
        key_name: str = "",
    ) -> str:
        """Type text (with Chinese/Unicode support) or simulate hardware keys on Android."""
        action_clean = action.strip().lower()
        if action_clean == "type":
            if not text:
                return "Error: 'text' cannot be empty for action='type'."
            res = await active_bridge.type_text(text=text)
            return res.message
        elif action_clean == "key":
            key_map: dict[str, KeyCode] = {
                "home": KeyCode.HOME,
                "back": KeyCode.BACK,
                "enter": KeyCode.ENTER,
                "power": KeyCode.POWER,
                "app_switch": KeyCode.APP_SWITCH,
                "volume_up": KeyCode.VOLUME_UP,
                "volume_down": KeyCode.VOLUME_DOWN,
                "menu": KeyCode.MENU,
                "notification": KeyCode.NOTIFICATION,
            }
            code = key_map.get(key_name.strip().lower())
            if not code:
                return f"Unsupported key name: '{key_name}'. Supported: {', '.join(key_map.keys())}."
            res = await active_bridge.press_key(code)
            return res.message
        return f"Unknown input action: '{action}'. Use 'type' or 'key'."

    # ---------------- 5. App Lifecycle Tool ----------------
    class AppInput(BaseModel):
        action: str = Field(
            description="App action: 'launch' (open app by package or alias like 'wechat','feishu','browser','settings'), 'terminate' (force stop app), 'current' (get foreground app).",
        )
        app_name_or_package: str = Field(
            default="",
            description="App package name or friendly alias (e.g. 'wechat', 'feishu', 'settings', 'browser', 'com.tencent.mm').",
        )

    @tool("mobile_app_tool", args_schema=AppInput)
    async def mobile_app_tool(
        action: str,
        app_name_or_package: str = "",
    ) -> str:
        """Launch, terminate, or inspect foreground Android applications."""
        action_clean = action.strip().lower()
        if action_clean == "launch":
            if not app_name_or_package:
                return "Error: 'app_name_or_package' is required for action='launch'."
            res = await active_bridge.launch_app(app_name_or_package)
            return res.message
        elif action_clean == "terminate":
            if not app_name_or_package:
                return "Error: 'app_name_or_package' is required for action='terminate'."
            res = await active_bridge.terminate_app(app_name_or_package)
            return res.message
        elif action_clean == "current":
            pkg, act = await active_bridge.get_current_app()
            return f"Foreground Application: Package='{pkg}', Activity='{act}'"
        return f"Unknown app action: '{action}'. Use 'launch', 'terminate', or 'current'."

    return [
        mobile_device_tool,
        mobile_snapshot_tool,
        mobile_touch_tool,
        mobile_input_tool,
        mobile_app_tool,
    ]
