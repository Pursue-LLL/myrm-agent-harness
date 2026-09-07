"""Unit tests for Mobile ADB Toolkit in harness.

Covers:
- ADBExecutor command parsing & execution
- MobilePerceptionEngine (UI hierarchy parsing & screen size)
- MobileExecutionEngine (tap, swipe, keypress, app launch)
- MobileADBSession (pairing, connect, snapshot, interact)
- LangChain agent tools creation
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.mobile_adb import (
    ADBExecutor,
    MobileActionResult,
    MobileADBSession,
    MobileBridgeConfig,
    MobileDeviceInfo,
    MobileScreenInfo,
    MobileUIElement,
    create_mobile_adb_session,
    create_mobile_adb_tools,
)
from myrm_agent_harness.toolkits.mobile_adb.execution import MobileExecutionEngine
from myrm_agent_harness.toolkits.mobile_adb.perception import MobilePerceptionEngine


@pytest.mark.asyncio
async def test_adb_executor_resolve_and_run():
    config = MobileBridgeConfig(adb_path="adb", command_timeout_seconds=5.0)
    executor = ADBExecutor(config)

    with patch("shutil.which", return_value="/opt/android/bin/adb"):
        assert executor.resolve_adb() == "/opt/android/bin/adb"

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc_mock = AsyncMock()
        proc_mock.communicate.return_value = (b"List of devices attached\n192.168.1.50:5555 device\n", b"")
        proc_mock.returncode = 0
        mock_exec.return_value = proc_mock

        rc, stdout, stderr = await executor.run_adb(["devices"])
        assert rc == 0
        assert "192.168.1.50:5555" in stdout
        assert stderr == ""


@pytest.mark.asyncio
async def test_mobile_perception_get_screen_info():
    executor = MagicMock(spec=ADBExecutor)
    executor.run_adb = AsyncMock(
        side_effect=[
            (0, "Physical size: 1080x2400", ""),
            (0, "Physical density: 420", ""),
        ]
    )

    perception = MobilePerceptionEngine(executor)
    screen_info = await perception.get_screen_info("192.168.1.50:5555")

    assert screen_info is not None
    assert screen_info.width == 1080
    assert screen_info.height == 2400
    assert screen_info.density_dpi == 420


@pytest.mark.asyncio
async def test_mobile_perception_dump_ui_hierarchy():
    executor = MagicMock(spec=ADBExecutor)
    fake_xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.android.settings" content-desc="" bounds="[0,0][1080,2400]">
    <node index="0" text="Wi-Fi" resource-id="com.android.settings:id/title" class="android.widget.TextView" package="com.android.settings" content-desc="Network setup" clickable="true" bounds="[100,200][500,300]" />
    <node index="1" text="" resource-id="com.android.settings:id/search" class="android.widget.EditText" package="com.android.settings" content-desc="Search settings" editable="true" bounds="[100,400][900,550]" />
  </node>
</hierarchy>
"""
    executor.run_adb = AsyncMock(
        side_effect=[
            (0, "UI hierchary dumped to: /data/local/tmp/uidump.xml", ""),
            (0, fake_xml, ""),
            (0, "", ""),  # cleanup rm
        ]
    )

    perception = MobilePerceptionEngine(executor)
    elements = await perception.dump_ui_hierarchy("192.168.1.50:5555")

    assert len(elements) == 2
    el1 = elements[0]
    assert el1.ref_id == "@m1"
    assert el1.text == "Wi-Fi"
    assert el1.is_clickable is True
    assert el1.center_x == 300
    assert el1.center_y == 250

    el2 = elements[1]
    assert el2.ref_id == "@m2"
    assert el2.is_editable is True
    assert el2.content_desc == "Search settings"


@pytest.mark.asyncio
async def test_mobile_execution_actions():
    executor = MagicMock(spec=ADBExecutor)
    executor.run_adb = AsyncMock(return_value=(0, "Success", ""))

    execution = MobileExecutionEngine(executor)

    tap_res = await execution.tap("dev1", 100, 200)
    assert tap_res.success is True
    assert "Tapped at (100, 200)" in tap_res.message

    swipe_res = await execution.swipe("dev1", 100, 500, 100, 100, 300)
    assert swipe_res.success is True

    type_res = await execution.type_text("dev1", "Hello World")
    assert type_res.success is True
    # Verify space escaping in input command
    call_args = executor.run_adb.call_args[0][0]
    assert "Hello%sWorld" in call_args

    key_res = await execution.press_key("dev1", 4)  # Back button
    assert key_res.success is True

    app_res = await execution.launch_app("dev1", "com.tencent.mm")
    assert app_res.success is True


@pytest.mark.asyncio
async def test_mobile_adb_session_and_agent_tools():
    session = create_mobile_adb_session()
    session.executor = MagicMock(spec=ADBExecutor)

    # Mock pairing
    session.executor.run_adb = AsyncMock(
        return_value=(0, "Successfully paired to 192.168.1.50:37891 [guid: ...]", "")
    )
    ok, msg = await session.pair_wireless_device("192.168.1.50", 37891, "123456")
    assert ok is True
    assert "Successfully paired" in msg

    # Create tools
    tools = create_mobile_adb_tools(session)
    assert len(tools) == 3

    tool_names = [t.name for t in tools]
    assert "mobile_snapshot_tool" in tool_names
    assert "mobile_interact_tool" in tool_names
    assert "mobile_device_manage_tool" in tool_names
