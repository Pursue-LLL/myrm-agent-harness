"""Unit tests for mobile_adb toolkit components."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.mobile_adb.mobile_agent_tools import (
    create_mobile_adb_tools,
)
from myrm_agent_harness.toolkits.mobile_adb.parser import MobileUIParser
from myrm_agent_harness.toolkits.mobile_adb.session import MobileSession
from myrm_agent_harness.toolkits.mobile_adb.types import (
    MobileActionResult,
    MobileDeviceConnectionStatus,
    MobileDeviceState,
)

SAMPLE_UIAUTOMATOR_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.android.settings" content-desc="" checkable="false" checked="false" clickable="false" enabled="true" focusable="false" focused="false" scrollable="false" long-clickable="false" password="false" selected="false" bounds="[0,0][1080,2400]">
    <node index="0" text="Network &amp; internet" resource-id="android:id/title" class="android.widget.TextView" package="com.android.settings" content-desc="Wi-Fi, mobile, hotspot" checkable="false" checked="false" clickable="true" enabled="true" focusable="true" focused="false" scrollable="false" long-clickable="false" password="false" selected="false" bounds="[100,200][980,350]" />
    <node index="1" text="Connected devices" resource-id="android:id/title" class="android.widget.TextView" package="com.android.settings" content-desc="Bluetooth, pairing" checkable="false" checked="false" clickable="true" enabled="true" focusable="true" focused="false" scrollable="false" long-clickable="false" password="false" selected="false" bounds="[100,360][980,510]" />
    <node index="2" text="Search settings" resource-id="com.android.settings:id/search_action_bar_title" class="android.widget.EditText" package="com.android.settings" content-desc="" checkable="false" checked="false" clickable="true" enabled="true" focusable="true" focused="true" scrollable="false" long-clickable="true" password="false" selected="false" bounds="[50,80][1030,180]" />
  </node>
</hierarchy>
"""


def test_mobile_ui_parser_bounds() -> None:
    left, top, right, bottom = MobileUIParser.parse_bounds("[100,200][980,350]")
    assert (left, top, right, bottom) == (100, 200, 980, 350)

    # Invalid bounds fallback
    assert MobileUIParser.parse_bounds("invalid") == (0, 0, 0, 0)


def test_mobile_ui_parser_xml_tree() -> None:
    elements, ref_map = MobileUIParser.parse_xml_tree(SAMPLE_UIAUTOMATOR_XML)
    assert len(elements) == 3
    assert "@mref_1" in ref_map
    assert "@mref_2" in ref_map
    assert "@mref_3" in ref_map

    first = ref_map["@mref_1"]
    assert first.text == "Network & internet"
    assert first.content_desc == "Wi-Fi, mobile, hotspot"
    assert first.center == (540, 275)
    assert first.clickable is True

    search_input = ref_map["@mref_3"]
    assert search_input.editable is True
    assert "Search settings" in search_input.to_summary()


@pytest.mark.asyncio
async def test_mobile_session_and_tools_factory() -> None:
    session = MobileSession(default_device="192.168.1.100:5555")
    assert session.get_target() == "192.168.1.100:5555"

    tools = create_mobile_adb_tools(session)
    assert len(tools) == 3
    tool_names = {t.name for t in tools}
    assert tool_names == {
        "mobile_snapshot_tool",
        "mobile_interact_tool",
        "mobile_global_tool",
    }


def test_mobile_safety_guard() -> None:
    from myrm_agent_harness.toolkits.mobile_adb.safety import MobileSafetyGuard

    guard = MobileSafetyGuard()

    # Package check
    allowed, _ = guard.is_package_allowed("com.tencent.mm")
    assert allowed is True

    blocked, reason = guard.is_package_allowed("com.android.settings.password")
    assert blocked is False
    assert "blocked by security policy" in reason

    # Input check
    safe_input, _ = guard.is_input_safe("Hello World 123")
    assert safe_input is True

    unsafe_input, reason = guard.is_input_safe("text; rm -rf /")
    assert unsafe_input is False
    assert "potentially malicious" in reason

    # Key check
    safe_key, _ = guard.is_key_safe("KEYCODE_HOME")
    assert safe_key is True

    unsafe_key, reason = guard.is_key_safe("POWER")
    assert unsafe_key is False
    assert "restricted for safety" in reason

    # UI risk check
    is_risky, reason = guard.evaluate_ui_risk(
        current_package="com.android.settings",
        elements=[],
        raw_xml="<node text='请输入支付密码' />",
    )
    assert is_risky is True
    assert "Sensitive action barrier triggered" in (reason or "")


@pytest.mark.asyncio
async def test_mobile_session_pair_and_connect_flow() -> None:
    session = MobileSession(default_device="")
    with pytest.MonkeyPatch.context() as mp:
        from unittest.mock import AsyncMock
        mock_pair = AsyncMock(return_value=MobileActionResult(success=True, action="pair", message="Successfully paired"))
        mock_connect = AsyncMock(return_value=MobileActionResult(success=True, action="connect", message="connected to 192.168.1.100:5555"))
        mp.setattr(session.driver, "pair", mock_pair)
        mp.setattr(session.driver, "connect", mock_connect)

        pair_res = await session.pair_device("192.168.1.100", 37123, "123456")
        assert pair_res.success is True

        conn_res = await session.connect_device("192.168.1.100", 5555)
        assert conn_res.success is True
        assert session.default_device == "192.168.1.100:5555"
        assert "192.168.1.100:5555" in session._connected_devices


def test_compress_screencap_bytes_passthrough_for_small_payloads() -> None:
    from myrm_agent_harness.toolkits.mobile_adb.compressor import compress_screencap_bytes

    # Sub-64-byte payloads are returned untouched (not a real image).
    assert compress_screencap_bytes(b"") == b""
    assert compress_screencap_bytes(b"short") == b"short"


def test_compress_screencap_bytes_downscales_real_png() -> None:
    import io

    from PIL import Image

    from myrm_agent_harness.toolkits.mobile_adb.compressor import compress_screencap_bytes

    source = Image.new("RGB", (2560, 1440), color=(20, 120, 200))
    buffer = io.BytesIO()
    source.save(buffer, format="PNG")

    compressed = compress_screencap_bytes(buffer.getvalue(), max_dimension=1280)

    result = Image.open(io.BytesIO(compressed))
    assert max(result.size) == 1280
    assert len(compressed) < len(buffer.getvalue())


@pytest.mark.asyncio
async def test_inject_text_utf8_uses_fast_path_for_ascii() -> None:
    from myrm_agent_harness.toolkits.mobile_adb.text_injection import inject_text_utf8

    commands: list[str] = []

    async def _run(shell_cmd: str) -> tuple[int, str, str]:
        commands.append(shell_cmd)
        return 0, "ok", ""

    ok, _ = await inject_text_utf8(_run, "Hello123")
    assert ok is True
    assert commands == ["input text Hello123"]


@pytest.mark.asyncio
async def test_inject_text_utf8_escapes_cjk_through_clipboard() -> None:
    from myrm_agent_harness.toolkits.mobile_adb.text_injection import inject_text_utf8

    commands: list[str] = []

    async def _run(shell_cmd: str) -> tuple[int, str, str]:
        commands.append(shell_cmd)
        return 0, "", ""

    ok, _ = await inject_text_utf8(_run, "你好 世界")
    assert ok is True
    # CJK + space must not go through the naive `input text` fast path.
    assert len(commands) == 1
    assert "base64 -d" in commands[0]
    assert "clipper.set" in commands[0]


@pytest.mark.asyncio
async def test_inject_text_utf8_reports_failure_when_all_routes_fail() -> None:
    from myrm_agent_harness.toolkits.mobile_adb.text_injection import inject_text_utf8

    async def _run(shell_cmd: str) -> tuple[int, str, str]:
        return 1, "", "error"

    ok, detail = await inject_text_utf8(_run, "你好")
    assert ok is False
    assert "error" in detail


@pytest.mark.asyncio
async def test_swipe_invalid_offset_returns_invalid_param() -> None:
    from unittest.mock import AsyncMock

    from myrm_agent_harness.toolkits.mobile_adb.driver import AdbDeviceDriver
    from myrm_agent_harness.toolkits.mobile_adb.parser import MobileUIParser

    elements, ref_map = MobileUIParser.parse_xml_tree(SAMPLE_UIAUTOMATOR_XML)
    driver = AdbDeviceDriver()
    driver._current_ref_map = ref_map
    driver._run_adb = AsyncMock(return_value=(0, "", ""))  # type: ignore[method-assign]

    bad = await driver.execute_semantic_action("t", "@mref_1", "swipe", "bad-offset")
    assert bad.success is False
    assert bad.error == "INVALID_PARAM"
    driver._run_adb.assert_not_awaited()

    ok = await driver.execute_semantic_action("t", "@mref_1", "swipe", "0,-600")
    assert ok.success is True

    stale = await driver.execute_semantic_action("t", "@mref_999", "click")
    assert stale.success is False
    assert stale.error == "ELEMENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_snapshot_settle_ms_capped_at_two_seconds() -> None:
    import asyncio
    from unittest.mock import AsyncMock, patch


    session = MobileSession(default_device="t")
    state = MobileDeviceState(
        device_id="t",
        ip_address="t",
        port=5555,
        connection_status=MobileDeviceConnectionStatus.CONNECTED,
    )
    session.driver.get_device_state = AsyncMock(return_value=state)  # type: ignore[method-assign]
    with patch.object(asyncio, "sleep", new=AsyncMock()) as nap:
        await session.snapshot(target="t", settle_ms=9000)
        nap.assert_awaited_once_with(2.0)



