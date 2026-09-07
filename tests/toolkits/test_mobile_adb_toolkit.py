from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.mobile_adb import (
    ADBExecutor,
    MobileActionResult,
    MobileADBSession,
    MobileBridgeConfig,
    MobileDeviceInfo,
    create_mobile_adb_session,
    create_mobile_adb_tools,
)
from myrm_agent_harness.toolkits.mobile_adb.execution import MobileExecutionEngine
from myrm_agent_harness.toolkits.mobile_adb.perception import MobilePerceptionEngine


@pytest.mark.asyncio
async def test_adb_executor_resolve():
    executor = ADBExecutor()
    bin_path = executor.resolve_adb()
    assert bin_path is not None


@pytest.mark.asyncio
async def test_mobile_session_list_devices():
    session = create_mobile_adb_session()
    fake_devices_output = (
        "List of devices attached\n"
        "192.168.1.50:5555 device product:redfin model:Pixel_5 device:redfin\n"
        "emulator-5554 unauthorized\n"
    )

    with patch.object(session.executor, "run_adb", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (0, fake_devices_output, "")
        devices = await session.list_devices()

    assert len(devices) == 2
    assert devices[0].device_id == "192.168.1.50:5555"
    assert devices[0].host == "192.168.1.50"
    assert devices[0].port == 5555
    assert devices[0].model == "Pixel_5"
    assert devices[0].state == "connected"
    assert devices[1].state == "unauthorized"


@pytest.mark.asyncio
async def test_mobile_session_pairing_and_connect():
    session = create_mobile_adb_session()

    # 1. Pair
    with patch.object(session.executor, "run_adb", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (0, "Successfully paired to 192.168.1.50:37891 [guid: ...]", "")
        ok, msg = await session.pair_wireless_device("192.168.1.50", 37891, "123456")
        assert ok is True
        assert "Successfully paired" in msg

    # 2. Connect
    with patch.object(session.executor, "run_adb", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = [
            (0, "connected to 192.168.1.50:5555", ""),
            (0, "Physical size: 1080x2400", ""),
            (0, "Physical density: 420", ""),
        ]
        ok, msg = await session.connect_device("192.168.1.50", 5555)
        assert ok is True
        assert session.active_device is not None
        assert session.active_device.device_id == "192.168.1.50:5555"
        assert session.active_device.screen_info is not None
        assert session.active_device.screen_info.width == 1080
        assert session.active_device.screen_info.height == 2400


@pytest.mark.asyncio
async def test_mobile_session_snapshot_and_interact():
    session = create_mobile_adb_session()
    session._active_device = MobileDeviceInfo(
        device_id="192.168.1.50:5555",
        host="192.168.1.50",
        port=5555,
        state="connected",
    )

    fake_xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
    <hierarchy rotation="0">
        <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.android.settings" bounds="[0,0][1080,2400]">
            <node index="0" text="Wi-Fi" resource-id="com.android.settings:id/title" class="android.widget.TextView" package="com.android.settings" bounds="[100,200][400,300]" clickable="true" />
            <node index="1" text="" content-desc="Search" resource-id="com.android.settings:id/search_button" class="android.widget.Button" package="com.android.settings" bounds="[900,100][1000,200]" clickable="true" />
        </node>
    </hierarchy>
    """

    with (
        patch.object(session.perception, "dump_ui_hierarchy", new_callable=AsyncMock) as mock_dump,
        patch.object(session.execution, "tap", new_callable=AsyncMock) as mock_tap,
    ):
        from myrm_agent_harness.toolkits.mobile_adb.types import MobileUIElement

        mock_dump.return_value = [
            MobileUIElement(
                ref_id="@m1",
                resource_id="com.android.settings:id/title",
                class_name="android.widget.TextView",
                package_name="com.android.settings",
                text="Wi-Fi",
                content_desc="",
                bounds=(100, 200, 400, 300),
                center_x=250,
                center_y=250,
                is_clickable=True,
                is_editable=False,
                is_scrollable=False,
                is_focused=False,
            )
        ]
        mock_tap.return_value = MobileActionResult(
            success=True,
            message="Tapped at (250, 250)",
            elapsed_ms=12.5,
        )

        # 1. Snapshot
        res = await session.snapshot(include_screenshot=False)
        assert res.success is True
        assert "@m1" in res.message
        assert "Wi-Fi" in res.message

        # 2. Interact via ref_id @m1
        act_res = await session.interact(action="tap", ref_id="@m1")
        assert act_res.success is True
        mock_tap.assert_called_once_with("192.168.1.50:5555", 250, 250)


@pytest.mark.asyncio
async def test_mobile_agent_tools():
    session = create_mobile_adb_session()
    tools = create_mobile_adb_tools(session)
    assert len(tools) == 3

    tool_names = [t.name for t in tools]
    assert "mobile_snapshot_tool" in tool_names
    assert "mobile_interact_tool" in tool_names
    assert "mobile_device_manage_tool" in tool_names
