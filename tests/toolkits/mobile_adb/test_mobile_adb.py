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
    MobileUIElement,
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
