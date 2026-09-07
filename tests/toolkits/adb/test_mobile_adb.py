"""Unit and integration tests for Mobile Wireless ADB toolkit."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from myrm_agent_harness.agent.tool_management.tool_layers import (
    ToolLayer,
    get_tool_layer,
    get_tool_replay_safety,
)
from myrm_agent_harness.agent.tool_management.types import ReplaySafety
from myrm_agent_harness.toolkits.adb import (
    AdbBridgeEngine,
    AdbCommandResult,
    AdbDeviceSnapshot,
    AdbElementNode,
    AdbSafetyGuard,
    AdbTouchAction,
    DeviceConnectionState,
    create_mobile_adb_tools,
)


def test_tool_layer_registration() -> None:
    """Verify that mobile tools are cleanly registered in EXTENDED layer with correct replay safety."""
    assert get_tool_layer("mobile_screencap_tool") == ToolLayer.EXTENDED
    assert get_tool_layer("mobile_ui_dump_tool") == ToolLayer.EXTENDED
    assert get_tool_layer("mobile_input_tool") == ToolLayer.EXTENDED
    assert get_tool_layer("mobile_launch_app_tool") == ToolLayer.EXTENDED

    assert get_tool_replay_safety("mobile_screencap_tool") == ReplaySafety.SAFE
    assert get_tool_replay_safety("mobile_ui_dump_tool") == ReplaySafety.SAFE
    assert get_tool_replay_safety("mobile_input_tool") == ReplaySafety.NEVER


def test_adb_safety_guard_blocks_sensitive() -> None:
    """Verify safety guard blocks system password, credentials and dangerous input."""
    # Package guard
    safe, msg = AdbSafetyGuard.is_package_allowed("com.android.settings.password")
    assert not safe
    assert "blocked by security policy" in msg

    safe, _ = AdbSafetyGuard.is_package_allowed("com.tencent.mm")
    assert safe

    # Input guard
    safe, msg = AdbSafetyGuard.is_input_safe("normal hello world")
    assert safe

    safe, msg = AdbSafetyGuard.is_input_safe("test; rm -rf /")
    assert not safe
    assert "malicious" in msg

    # Keycode guard
    safe, msg = AdbSafetyGuard.is_key_safe("POWER")
    assert not safe

    safe, _ = AdbSafetyGuard.is_key_safe("KEYCODE_BACK")
    assert safe


@pytest.mark.asyncio
async def test_adb_element_node_center() -> None:
    """Verify element center coordinate calculation."""
    node = AdbElementNode(
        ref_id="@mref_1",
        text="Submit",
        bounds=(100, 200, 300, 400),
        clickable=True,
    )
    assert node.center == (200, 300)


@pytest.mark.asyncio
async def test_adb_bridge_engine_lifecycle() -> None:
    """Test engine pairing, connect, snapshot, and input execution."""
    engine = AdbBridgeEngine(device_address="192.168.1.50:5555")

    with patch.object(
        engine,
        "execute_raw",
        new_callable=AsyncMock,
    ) as mock_exec:
        # 1. Pairing
        mock_exec.return_value = AdbCommandResult(
            success=True,
            output="Successfully paired to 192.168.1.50:5555 [guid=...]",
        )
        res = await engine.pair_wireless("192.168.1.50:5555", "123456")
        assert res.success
        assert engine.state == DeviceConnectionState.CONNECTED

        # 2. Input injection
        mock_exec.return_value = AdbCommandResult(success=True, output="")
        tap_res = await engine.send_input(AdbTouchAction.TAP, x=100, y=200)
        assert tap_res.success

        # 3. Launch app
        launch_res = await engine.launch_app("com.example.app")
        assert launch_res.success


@pytest.mark.asyncio
async def test_create_mobile_adb_tools() -> None:
    """Test LangChain tool surface execution and response formatting."""
    engine = AdbBridgeEngine(device_address="192.168.1.50:5555")
    tools = create_mobile_adb_tools(engine)
    assert len(tools) == 4

    tool_map = {t.name: t for t in tools}

    # Test screencap
    with patch.object(
        engine,
        "get_device_snapshot",
        new_callable=AsyncMock,
    ) as mock_snap:
        mock_snap.return_value = AdbDeviceSnapshot(
            package_name="com.test.app",
            activity_name="MainActivity",
            screenshot_bytes=b"fake-bytes",
            screenshot_base64="ZmFrZQ==",
            elements=[
                AdbElementNode(
                    ref_id="@mref_1",
                    text="Login",
                    bounds=(10, 20, 110, 80),
                    clickable=True,
                )
            ],
        )

        cap_tool = tool_map["mobile_screencap_tool"]
        out = await cap_tool.ainvoke({"include_base64": False})
        assert "Mobile screen captured successfully" in out
        assert "com.test.app" in out

        dump_tool = tool_map["mobile_ui_dump_tool"]
        dump_out = await dump_tool.ainvoke({"filter_text": "Login"})
        assert "@mref_1" in dump_out
        assert "Login" in dump_out
