"""Unit tests for Mobile Android ADB Wireless Toolkit.

[INPUT]
- myrm_agent_harness.toolkits.mobile.* (POS: mobile toolkit modules)

[OUTPUT]
- Pytest test suite validating device lifecycle, UI parsing, touch & text input, safety barrier, and LangChain tools
"""

from __future__ import annotations

import base64
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from myrm_agent_harness.toolkits.mobile.device_manager import MobileDeviceManager
from myrm_agent_harness.toolkits.mobile.inspector import MobileInspector
from myrm_agent_harness.toolkits.mobile.input_controller import MobileInputController
from myrm_agent_harness.toolkits.mobile.app_manager import MobileAppManager
from myrm_agent_harness.toolkits.mobile.mobile_bridge import create_mobile_bridge
from myrm_agent_harness.toolkits.mobile.mobile_agent_tools import create_mobile_tools
from myrm_agent_harness.toolkits.mobile.safety import MobileSafetyGuard
from myrm_agent_harness.toolkits.mobile.types import (
    DeviceConnectionStatus,
    DeviceInfo,
    UIElementNode,
)

SAMPLE_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.android.settings" content-desc="" checkable="false" checked="false" clickable="false" enabled="true" focusable="false" focused="false" scrollable="false" long-clickable="false" password="false" selected="false" bounds="[0,0][1080,2400]">
    <node index="0" text="Wi-Fi" resource-id="com.android.settings:id/title" class="android.widget.TextView" package="com.android.settings" content-desc="Network and internet" checkable="false" checked="false" clickable="true" enabled="true" focusable="true" focused="false" scrollable="false" long-clickable="true" password="false" selected="false" bounds="[100,200][980,350]" />
    <node index="1" text="Bluetooth" resource-id="com.android.settings:id/title" class="android.widget.TextView" package="com.android.settings" content-desc="" checkable="false" checked="false" clickable="true" enabled="true" focusable="true" focused="false" scrollable="false" long-clickable="false" password="false" selected="false" bounds="[100,400][980,550]" />
  </node>
</hierarchy>
"""


@pytest.mark.asyncio
async def test_device_manager_enumeration() -> None:
    dm = MobileDeviceManager()
    with patch.object(
        dm,
        "execute_adb_command",
        new=AsyncMock(
            return_value=(
                0,
                b"List of devices attached\n192.168.1.100:5555  device product:pixel model:Pixel_7 device:panther\n",
                b"",
            )
        ),
    ):
        devs = await dm.list_devices()
        assert len(devs) == 1
        dev = devs[0]
        assert dev.serial == "192.168.1.100:5555"
        assert dev.status == DeviceConnectionStatus.CONNECTED
        assert dev.is_wireless is True
        assert dev.ip_address == "192.168.1.100"
        assert dev.port == 5555


@pytest.mark.asyncio
async def test_device_manager_pairing_and_connection() -> None:
    dm = MobileDeviceManager()
    with patch.object(
        dm,
        "execute_adb_command",
        new=AsyncMock(return_value=(0, b"Successfully paired to 192.168.1.100:37891", b"")),
    ):
        ok = await dm.pair_wireless("192.168.1.100", 37891, "123456")
        assert ok is True

    with patch.object(
        dm,
        "execute_adb_command",
        new=AsyncMock(return_value=(0, b"connected to 192.168.1.100:5555", b"")),
    ):
        connected = await dm.connect_wireless("192.168.1.100", 5555)
        assert connected is True


@pytest.mark.asyncio
async def test_inspector_ui_dump_and_parsing() -> None:
    dm = MobileDeviceManager()
    dm._default_serial = "192.168.1.100:5555"
    inspector = MobileInspector(dm)

    async def fake_exec(args: list[str], **kwargs):
        if "dumpsys" in args:
            return 0, b"mResumedActivity: ActivityRecord{123 u0 com.android.settings/.SettingsActivity}", b""
        if "cat" in args and "/data/local/tmp/ui_dump.xml" in args:
            return 0, SAMPLE_XML.encode("utf-8"), b""
        if "uiautomator" in args:
            return 0, b"UI hierchary dumped to: /data/local/tmp/ui_dump.xml", b""
        if "getprop" in args or "wm" in args:
            return 0, b"Physical size: 1080x2400\n", b""
        return 0, b"", b""

    with patch.object(dm, "execute_adb_command", side_effect=fake_exec):
        res = await inspector.dump_ui_hierarchy()
        assert res.top_package == "com.android.settings"
        assert res.top_activity == ".SettingsActivity"
        assert len(res.clickable_elements) == 2

        wifi_node = res.clickable_elements[0]
        assert wifi_node.text == "Wi-Fi"
        assert wifi_node.bounds == (100, 200, 980, 350)
        assert wifi_node.center_x == 540
        assert wifi_node.center_y == 275
        assert round(wifi_node.norm_x, 2) == 0.5


@pytest.mark.asyncio
async def test_input_controller_tap_and_swipe() -> None:
    dm = MobileDeviceManager()
    dm._default_serial = "192.168.1.100:5555"
    controller = MobileInputController(dm)

    recorded_cmds: list[list[str]] = []

    async def fake_exec(args: list[str], **kwargs):
        recorded_cmds.append(args)
        return 0, b"", b""

    with patch.object(dm, "execute_adb_command", side_effect=fake_exec):
        # 1. Tap with absolute pixels
        tap_res = await controller.tap(500, 1000)
        assert tap_res.success is True
        assert recorded_cmds[-1] == ["shell", "input", "tap", "500", "1000"]

        # 2. Swipe
        swipe_res = await controller.swipe(100, 200, 100, 800, duration_ms=400)
        assert swipe_res.success is True
        assert recorded_cmds[-1] == ["shell", "input", "swipe", "100", "200", "100", "800", "400"]

        # 3. Press Key
        key_res = await controller.press_key("HOME")
        assert key_res.success is True
        assert recorded_cmds[-1] == ["shell", "input", "keyevent", "3"]


@pytest.mark.asyncio
async def test_safety_barrier_guard() -> None:
    guard = MobileSafetyGuard()

    # Safe UI
    safe_node = UIElementNode(
        index=0,
        text="设置选项",
        resource_id="",
        class_name="",
        package="com.android.settings",
        content_desc="",
        checkable=False,
        checked=False,
        clickable=True,
        enabled=True,
        focusable=True,
        focused=False,
        scrollable=False,
        long_clickable=False,
        password=False,
        selected=False,
        bounds=(0, 0, 100, 100),
        center_x=50,
        center_y=50,
        norm_x=0.1,
        norm_y=0.1,
    )
    is_risky, reason = guard.evaluate_ui_risk("com.android.settings", [safe_node], "")
    assert is_risky is False
    assert reason is None

    # Sensitive payment UI
    pay_node = UIElementNode(
        index=0,
        text="确认付款 ￥99.00",
        resource_id="",
        class_name="",
        package="com.tencent.mm",
        content_desc="立即支付",
        checkable=False,
        checked=False,
        clickable=True,
        enabled=True,
        focusable=True,
        focused=False,
        scrollable=False,
        long_clickable=False,
        password=False,
        selected=False,
        bounds=(0, 0, 100, 100),
        center_x=50,
        center_y=50,
        norm_x=0.1,
        norm_y=0.1,
    )
    is_risky_pay, pay_reason = guard.evaluate_ui_risk("com.tencent.mm", [pay_node], "")
    assert is_risky_pay is True
    assert "Sensitive action barrier" in str(pay_reason)


@pytest.mark.asyncio
async def test_mobile_agent_tools_surface() -> None:
    bridge = create_mobile_bridge()
    tools = create_mobile_tools(bridge)
    tool_map = {t.name: t for t in tools}

    assert "mobile_screencap_tool" in tool_map
    assert "mobile_ui_dump_tool" in tool_map
    assert "mobile_input_tool" in tool_map
    assert "mobile_launch_app_tool" in tool_map

    with patch.object(
        bridge.inspector,
        "screencap",
        new=AsyncMock(
            return_value=MagicMock(
                image_bytes=b"fake_png_data",
                width=1080,
                height=2400,
                format="png",
                base64_data="ZmFrZQ==",
            )
        ),
    ):
        raw = await tool_map["mobile_screencap_tool"].ainvoke({"include_base64": True})
        parsed = json.loads(raw)
        assert parsed["success"] is True
        assert parsed["width"] == 1080
        assert parsed["base64_data"] == "ZmFrZQ=="
