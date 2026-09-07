"""Unit tests for Mobile ADB Bridge Toolkit.

[INPUT]
- myrm_agent_harness.toolkits.mobile

[OUTPUT]
- pytest suite for device manager, inspector, input controller, and agent tools

[POS]
myrm-agent-harness/tests/toolkits/mobile/test_mobile_adb_bridge.py
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from myrm_agent_harness.toolkits.mobile.app_manager import MobileAppManager
from myrm_agent_harness.toolkits.mobile.device_manager import AdbDeviceManager
from myrm_agent_harness.toolkits.mobile.input_controller import MobileInputController
from myrm_agent_harness.toolkits.mobile.inspector import MobileInspector
from myrm_agent_harness.toolkits.mobile.mobile_agent_tools import create_mobile_tools
from myrm_agent_harness.toolkits.mobile.types import (
    DeviceConnectionState,
    MobileDeviceInfo,
    MobileElementNode,
)


@pytest.mark.asyncio
async def test_adb_device_manager_list_devices() -> None:
    dm = AdbDeviceManager()
    sample_output = (
        "List of devices attached\n"
        "192.168.1.50:5555      device product:husky model:Pixel_8_Pro device:husky\n"
        "emulator-5554          device product:sdk_gphone model:Android_SDK device:generic\n"
    )

    with patch.object(dm, "_run_adb_cmd", new_callable=AsyncMock) as mock_cmd:
        # First call for devices -l, then enrich calls
        mock_cmd.side_effect = [
            (0, sample_output, ""),
            (0, "Physical size: 1080x2400", ""),
            (0, "14", ""),
            (0, "34", ""),
            (0, "level: 85", ""),
            (0, "Physical size: 1080x2400", ""),
            (0, "14", ""),
            (0, "34", ""),
            (0, "level: 100", ""),
        ]

        devices = await dm.list_devices()
        assert len(devices) == 2
        assert devices[0].serial == "192.168.1.50:5555"
        assert devices[0].connection_type == "wireless"
        assert devices[0].model == "Pixel 8 Pro"
        assert devices[0].battery_level == 85
        assert devices[0].state == DeviceConnectionState.CONNECTED


@pytest.mark.asyncio
async def test_adb_wireless_pairing_and_connect() -> None:
    dm = AdbDeviceManager()

    with patch.object(dm, "_run_adb_cmd", new_callable=AsyncMock) as mock_cmd:
        mock_cmd.return_value = (0, "Successfully paired to 192.168.1.50:37123 [guid=...]", "")
        ok = await dm.pair_wireless_device("192.168.1.50", 37123, "123456")
        assert ok is True

    with patch.object(dm, "_run_adb_cmd", new_callable=AsyncMock) as mock_cmd:
        mock_cmd.return_value = (0, "connected to 192.168.1.50:5555", "")
        with patch.object(dm, "list_devices", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = [
                MobileDeviceInfo(serial="192.168.1.50:5555", connection_type="wireless")
            ]
            dev = await dm.connect_device("192.168.1.50", 5555)
            assert dev is not None
            assert dev.serial == "192.168.1.50:5555"


@pytest.mark.asyncio
async def test_mobile_inspector_ui_dump_parsing() -> None:
    dm = MagicMock()
    dm.is_adb_available.return_value = True
    dm.execute_shell = AsyncMock()

    xml_mock = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hierarchy rotation="0">'
        '<node index="0" text="" resource-id="" class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">'
        '<node index="0" text="Settings" resource-id="android:id/title" class="android.widget.TextView" clickable="true" bounds="[100,200][400,300]"/>'
        '<node index="1" text="Search" resource-id="com.android.settings:id/search" class="android.widget.EditText" focusable="true" bounds="[100,400][980,500]"/>'
        '</node>'
        '</hierarchy>'
    )
    dm.execute_shell.return_value = xml_mock

    inspector = MobileInspector(dm)
    root, summary = await inspector.dump_ui_hierarchy("192.168.1.50:5555")

    assert root is not None
    assert len(root.children) == 2
    assert "Settings" in summary
    assert "Search" in summary
    assert "@node_1" in summary


@pytest.mark.asyncio
async def test_mobile_input_controller() -> None:
    dm = MagicMock()
    dm.execute_shell = AsyncMock(return_value="")
    input_ctrl = MobileInputController(dm)

    # Test tap
    ok = await input_ctrl.tap("test-device", 500, 800)
    assert ok is True
    dm.execute_shell.assert_called_with("test-device", "input tap 500 800")

    # Test swipe
    ok = await input_ctrl.swipe("test-device", 100, 200, 100, 800, duration_ms=400)
    assert ok is True
    dm.execute_shell.assert_called_with("test-device", "input swipe 100 200 100 800 400")

    # Test keyevent
    ok = await input_ctrl.press_key("test-device", "HOME")
    assert ok is True
    dm.execute_shell.assert_called_with("test-device", "input keyevent 3")


@pytest.mark.asyncio
async def test_mobile_app_manager() -> None:
    dm = MagicMock()
    dm.execute_shell = AsyncMock(return_value="Events injected: 1")
    app_mgr = MobileAppManager(dm)

    ok = await app_mgr.launch_app("test-device", "wechat")
    assert ok is True
    dm.execute_shell.assert_called_with(
        "test-device",
        "monkey -p com.tencent.mm -c android.intent.category.LAUNCHER 1",
    )


@pytest.mark.asyncio
async def test_mobile_agent_tools_execution() -> None:
    dm = MagicMock()
    dm.list_devices = AsyncMock(
        return_value=[
            MobileDeviceInfo(
                serial="192.168.1.50:5555",
                model="Pixel 8 Pro",
                connection_type="wireless",
            )
        ]
    )

    tools = create_mobile_tools(dm)
    assert len(tools) == 3

    connect_tool = next(t for t in tools if t.name == "mobile_device_connect")
    res_str = await connect_tool.ainvoke({"action": "list"})
    res = json.loads(res_str)
    assert res["count"] == 1
    assert res["devices"][0]["serial"] == "192.168.1.50:5555"
