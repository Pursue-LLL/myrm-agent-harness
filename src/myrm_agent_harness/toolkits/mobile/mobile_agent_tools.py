"""LangChain compatible Agent tool definitions for mobile Android device automation.

[INPUT]
- device_manager.py, inspector.py, input_controller.py, app_manager.py, types.py

[OUTPUT]
- create_mobile_tools, mobile_device_connect_tool, mobile_snapshot_tool, mobile_interact_tool

[POS]
High-level Agent tools exposing mobile connectivity, perception (visual + UI hierarchy), and interaction.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Literal
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from .app_manager import MobileAppManager
from .device_manager import AdbDeviceManager
from .input_controller import MobileInputController
from .inspector import MobileInspector
from .types import MobileActionResult, MobileKeyEvent, MobileTouchAction


# Pydantic Schemas for Tools
class MobileDeviceConnectInput(BaseModel):
    """Input for mobile device discovery, pairing, and connection."""

    action: Literal["list", "pair", "connect", "disconnect"] = Field(
        ...,
        description="Action to perform: 'list' (discover devices), 'pair' (Android 11+ pairing code), 'connect' (connect by IP:port), 'disconnect'.",
    )
    host: str | None = Field(
        None,
        description="IP address of the wireless Android device (e.g. '192.168.1.50').",
    )
    port: int | None = Field(
        None,
        description="Port number (e.g. 5555 for connect, or pairing port for pair).",
    )
    pairing_code: str | None = Field(
        None,
        description="6-digit pairing code from Android Wireless Debugging settings.",
    )
    serial: str | None = Field(
        None,
        description="Device serial (e.g. '192.168.1.50:5555' or USB serial).",
    )


class MobileSnapshotInput(BaseModel):
    """Input for mobile screen and UI hierarchy inspection."""

    serial: str = Field(..., description="Target device serial.")
    include_screenshot: bool = Field(
        True,
        description="Whether to capture and return Base64 image of the screen.",
    )
    include_ui_tree: bool = Field(
        True,
        description="Whether to dump and return the interactive UI element hierarchy.",
    )


class MobileInteractInput(BaseModel):
    """Input for mobile touch, gesture, text typing, and key events."""

    serial: str = Field(..., description="Target device serial.")
    action: Literal["tap", "swipe", "input_text", "press_key", "launch_app", "stop_app"] = Field(
        ...,
        description="Interaction action to perform.",
    )
    x: float | None = Field(
        None,
        description="X coordinate (absolute pixel integer or 0.0~1.0 normalized float).",
    )
    y: float | None = Field(
        None,
        description="Y coordinate (absolute pixel integer or 0.0~1.0 normalized float).",
    )
    end_x: float | None = Field(
        None,
        description="End X coordinate for swipe gesture.",
    )
    end_y: float | None = Field(
        None,
        description="End Y coordinate for swipe gesture.",
    )
    duration_ms: int = Field(300, description="Swipe duration in milliseconds.")
    text: str | None = Field(None, description="Text string to type into focused input.")
    key: MobileKeyEvent | None = Field(
        None,
        description="Hardware key to press ('HOME', 'BACK', 'APP_SWITCH', 'ENTER', etc.).",
    )
    package_or_alias: str | None = Field(
        None,
        description="App package or common alias (e.g. 'wechat', 'settings', 'chrome').",
    )
    is_normalized: bool = Field(
        False,
        description="Set to true if x/y coordinates are normalized (0.0~1.0).",
    )


def create_mobile_tools(
    device_manager: AdbDeviceManager | None = None,
) -> list[StructuredTool]:
    """Factory creating LangChain StructuredTools for mobile device automation."""
    dm = device_manager or AdbDeviceManager()
    inspector = MobileInspector(dm)
    input_ctrl = MobileInputController(dm)
    app_mgr = MobileAppManager(dm)

    async def _handle_device_connect(**kwargs: Any) -> str:
        action = kwargs.get("action")
        host = kwargs.get("host")
        port = kwargs.get("port")
        serial = kwargs.get("serial")
        code = kwargs.get("pairing_code")

        if action == "list":
            devices = await dm.list_devices()
            return json.dumps(
                {"devices": [d.to_dict() for d in devices], "count": len(devices)},
                ensure_ascii=False,
            )
        elif action == "pair":
            if not host or not port or not code:
                return "Error: 'host', 'port', and 'pairing_code' are required for pair action."
            ok = await dm.pair_wireless_device(host, port, code)
            return json.dumps(
                {"success": ok, "message": "Pairing succeeded" if ok else "Pairing failed"}
            )
        elif action == "connect":
            if not host or not port:
                return "Error: 'host' and 'port' are required for connect action."
            dev = await dm.connect_device(host, port)
            return json.dumps(
                {
                    "success": dev is not None,
                    "device": dev.to_dict() if dev else None,
                },
                ensure_ascii=False,
            )
        elif action == "disconnect":
            if not serial:
                return "Error: 'serial' is required for disconnect action."
            ok = await dm.disconnect_device(serial)
            return json.dumps({"success": ok})

        return f"Unknown action: {action}"

    async def _handle_snapshot(**kwargs: Any) -> str:
        serial = kwargs.get("serial", "")
        include_img = kwargs.get("include_screenshot", True)
        include_tree = kwargs.get("include_ui_tree", True)

        img_b64 = None
        tree_summary = None
        top_act = await inspector.get_top_activity(serial)

        if include_img:
            img_b64 = await inspector.capture_screenshot(serial)

        elem_count = 0
        if include_tree:
            root_node, tree_summary = await inspector.dump_ui_hierarchy(serial)
            if root_node:
                elem_count = len(root_node.children)

        res = MobileActionResult(
            success=True,
            message="Snapshot captured successfully",
            screenshot_base64=img_b64,
            ui_tree_summary=tree_summary,
            top_activity=top_act,
            element_count=elem_count,
        )
        return json.dumps(res.to_dict(), ensure_ascii=False)

    async def _handle_interact(**kwargs: Any) -> str:
        serial = kwargs.get("serial", "")
        action = kwargs.get("action")
        is_norm = kwargs.get("is_normalized", False)

        success = False
        msg = ""

        if action == "tap":
            x, y = kwargs.get("x"), kwargs.get("y")
            if x is None or y is None:
                return "Error: x and y are required for tap."
            success = await input_ctrl.tap(serial, x, y, is_normalized=is_norm)
            msg = f"Tapped at ({x}, {y})"
        elif action == "swipe":
            x1, y1 = kwargs.get("x"), kwargs.get("y")
            x2, y2 = kwargs.get("end_x"), kwargs.get("end_y")
            dur = kwargs.get("duration_ms", 300)
            if any(v is None for v in (x1, y1, x2, y2)):
                return "Error: start and end coordinates required for swipe."
            success = await input_ctrl.swipe(
                serial, x1, y1, x2, y2, duration_ms=dur, is_normalized=is_norm
            )
            msg = f"Swiped from ({x1},{y1}) to ({x2},{y2})"
        elif action == "input_text":
            text = kwargs.get("text", "")
            success = await input_ctrl.input_text(serial, text)
            msg = f"Typed text: {text}"
        elif action == "press_key":
            key = kwargs.get("key")
            if not key:
                return "Error: key is required for press_key."
            success = await input_ctrl.press_key(serial, key)
            msg = f"Pressed key: {key}"
        elif action == "launch_app":
            pkg = kwargs.get("package_or_alias", "")
            success = await app_mgr.launch_app(serial, pkg)
            msg = f"Launched app: {pkg}"
        elif action == "stop_app":
            pkg = kwargs.get("package_or_alias", "")
            success = await app_mgr.stop_app(serial, pkg)
            msg = f"Stopped app: {pkg}"
        else:
            return f"Unknown action: {action}"

        return json.dumps({"success": success, "message": msg}, ensure_ascii=False)

    return [
        StructuredTool.from_function(
            coroutine=_handle_device_connect,
            name="mobile_device_connect",
            description="Manage mobile Android device discovery, wireless pairing, and connection via ADB.",
            args_schema=MobileDeviceConnectInput,
        ),
        StructuredTool.from_function(
            coroutine=_handle_snapshot,
            name="mobile_snapshot",
            description="Capture Android screen visual bitmap and structural Accessibility UI element hierarchy.",
            args_schema=MobileSnapshotInput,
        ),
        StructuredTool.from_function(
            coroutine=_handle_interact,
            name="mobile_interact",
            description="Execute touch gestures, clicks, Chinese/Unicode typing, hardware keys, and app launches on Android.",
            args_schema=MobileInteractInput,
        ),
    ]
