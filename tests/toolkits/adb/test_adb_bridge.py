"""Unit tests for Mobile Wireless ADB toolkit.

[INPUT]
- myrm_agent_harness.toolkits.adb.*

[OUTPUT]
- TestAdbSafetyGuard: tests for package, input, and key safety checks
- TestAdbBridgeEngine: tests for pairing, connect, XML hierarchy dump, and input injection
- TestAdbAgentTools: tests for LangChain tool wrappers

[POS]
Test suite for mobile ADB capabilities.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
import pytest

from myrm_agent_harness.toolkits.adb.adb_agent_tools import create_mobile_adb_tools
from myrm_agent_harness.toolkits.adb.engine import AdbBridgeEngine
from myrm_agent_harness.toolkits.adb.safety import AdbSafetyGuard
from myrm_agent_harness.toolkits.adb.types import (
    AdbCommandResult,
    AdbTouchAction,
    DeviceConnectionState,
)


class TestAdbSafetyGuard:
    """Test zero-privilege security filters for mobile operations."""

    def test_package_allowed_check(self) -> None:
        allowed, _ = AdbSafetyGuard.is_package_allowed("com.tencent.mm")
        assert allowed is True

        blocked, reason = AdbSafetyGuard.is_package_allowed("com.android.settings.password")
        assert blocked is False
        assert "blocked by security policy" in reason

    def test_input_safe_check(self) -> None:
        safe, _ = AdbSafetyGuard.is_input_safe("Hello World 123")
        assert safe is True

        unsafe, reason = AdbSafetyGuard.is_input_safe("text; rm -rf /")
        assert unsafe is False
        assert "potentially malicious" in reason

        backtick_unsafe, _ = AdbSafetyGuard.is_input_safe("test `cat /etc/passwd`")
        assert backtick_unsafe is False

    def test_key_safe_check(self) -> None:
        safe, _ = AdbSafetyGuard.is_key_safe("KEYCODE_HOME")
        assert safe is True

        unsafe, reason = AdbSafetyGuard.is_key_safe("POWER")
        assert unsafe is False
        assert "restricted for safety" in reason


@pytest.mark.asyncio
class TestAdbBridgeEngine:
    """Test ADB bridge execution, parsing, and state transitions."""

    async def test_pair_and_connect_wireless(self) -> None:
        engine = AdbBridgeEngine(device_address="192.168.1.50:5555")

        with patch.object(
            engine,
            "execute_raw",
            new_callable=AsyncMock,
            return_value=AdbCommandResult(success=True, output="Successfully paired to 192.168.1.50:5555", elapsed_ms=120),
        ):
            res = await engine.pair_wireless("192.168.1.50:5555", "123456")
            assert res.success is True
            assert engine.state == DeviceConnectionState.CONNECTED

        with patch.object(
            engine,
            "execute_raw",
            new_callable=AsyncMock,
            return_value=AdbCommandResult(success=True, output="connected to 192.168.1.50:5555", elapsed_ms=80),
        ):
            res2 = await engine.connect_wireless("192.168.1.50:5555")
            assert res2.success is True
            assert engine.state == DeviceConnectionState.CONNECTED

    async def test_dump_ui_hierarchy_parsing(self) -> None:
        engine = AdbBridgeEngine(device_address="192.168.1.50:5555")
        sample_xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
        <hierarchy rotation="0">
          <node index="0" text="" resource-id="com.example:id/container" class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
            <node index="0" text="Login Button" resource-id="com.example:id/btn_login" class="android.widget.Button" bounds="[100,500][500,600]" clickable="true" />
            <node index="1" text="" content-desc="Avatar Profile" class="android.widget.ImageView" bounds="[50,100][150,200]" clickable="true" />
          </node>
        </hierarchy>"""

        with patch.object(
            engine,
            "execute_raw",
            new_callable=AsyncMock,
            return_value=AdbCommandResult(success=True, output=sample_xml),
        ):
            elements = await engine.dump_ui_hierarchy()
            assert len(elements) == 2
            btn = elements[0]
            assert btn.ref_id == "@mref_1"
            assert btn.text == "Login Button"
            assert btn.bounds == (100, 500, 500, 600)
            assert btn.center == (300, 550)
            assert btn.clickable is True

            avatar = elements[1]
            assert avatar.ref_id == "@mref_2"
            assert avatar.content_desc == "Avatar Profile"
            assert avatar.center == (100, 150)

    async def test_send_input_actions(self) -> None:
        engine = AdbBridgeEngine(device_address="192.168.1.50:5555")

        with patch.object(
            engine,
            "execute_raw",
            new_callable=AsyncMock,
            return_value=AdbCommandResult(success=True, output="", elapsed_ms=10),
        ) as mock_raw:
            res_tap = await engine.send_input(AdbTouchAction.TAP, x=300, y=550)
            assert res_tap.success is True
            mock_raw.assert_called_with("shell", "input", "tap", "300", "550")

            res_swipe = await engine.send_input(AdbTouchAction.SWIPE, x=500, y=1000, end_x=500, end_y=200, duration_ms=500)
            assert res_swipe.success is True
            mock_raw.assert_called_with("shell", "input", "swipe", "500", "1000", "500", "200", "500")

            res_text = await engine.send_input(AdbTouchAction.TEXT_INPUT, text="Hello World")
            assert res_text.success is True
            mock_raw.assert_called_with("shell", "input", "text", "Hello%sWorld")

    async def test_launch_app_security(self) -> None:
        engine = AdbBridgeEngine(device_address="192.168.1.50:5555")
        res_blocked = await engine.launch_app("com.android.settings.password")
        assert res_blocked.success is False
        assert "blocked by security policy" in res_blocked.error


@pytest.mark.asyncio
class TestAdbAgentTools:
    """Test LangChain mobile tool wrapper execution."""

    async def test_create_and_invoke_tools(self) -> None:
        engine = AdbBridgeEngine(device_address="192.168.1.50:5555")
        tools = {t.name: t for t in create_mobile_adb_tools(engine)}
        assert "mobile_screencap_tool" in tools
        assert "mobile_ui_dump_tool" in tools
        assert "mobile_input_tool" in tools
        assert "mobile_launch_app_tool" in tools

        with patch.object(
            engine,
            "capture_screenshot",
            new_callable=AsyncMock,
            return_value=(b"\x89PNGfakeimage", "iVBORw0KGgoAAAANSUhEUgAA"),
        ), patch.object(
            engine,
            "execute_raw",
            new_callable=AsyncMock,
            return_value=AdbCommandResult(success=True, output="mCurrentFocus=Window{123 u0 com.tencent.mm/com.tencent.mm.ui.LauncherUI}"),
        ):
            screencap_tool = tools["mobile_screencap_tool"]
            out = await screencap_tool.ainvoke({"include_base64": False})
            assert "Mobile screen captured successfully" in out
            assert "com.tencent.mm" in out
