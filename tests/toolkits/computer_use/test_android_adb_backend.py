"""Tests for Android ADB Wireless backend & primitives."""

import pytest
from unittest.mock import AsyncMock, patch

from myrm_agent_harness.toolkits.computer_use.backends.android.client import AndroidAdbClient
from myrm_agent_harness.toolkits.computer_use.backends.android.tree_pruner import AndroidUiPruner, MobileNode
from myrm_agent_harness.toolkits.computer_use.backends.android.compressor import compress_screencap_bytes
from myrm_agent_harness.toolkits.computer_use.backends.android.driver import AndroidAdbBackend


def test_tree_pruner_parses_interactive_nodes() -> None:
    sample_xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.android.settings" bounds="[0,0][1080,2400]">
    <node index="0" text="Settings" resource-id="com.android.settings:id/title" class="android.widget.TextView" bounds="[100,200][400,280]" clickable="false" />
    <node index="1" text="" content-desc="Search settings" resource-id="com.android.settings:id/search_action_bar" class="android.widget.Button" bounds="[100,300][980,420]" clickable="true" />
    <node index="2" text="Search query" class="android.widget.EditText" bounds="[100,450][980,550]" focusable="true" clickable="true" />
  </node>
</hierarchy>"""

    nodes = AndroidUiPruner.extract_interactive_nodes(sample_xml)
    assert len(nodes) == 3

    # Check search button
    btn_node = nodes[1]
    assert btn_node.content_desc == "Search settings"
    assert btn_node.clickable is True
    assert btn_node.center == (540, 360)

    # Check edit text
    edit_node = nodes[2]
    assert edit_node.editable is True
    assert edit_node.center == (540, 500)

    summary = AndroidUiPruner.to_markdown_summary(nodes)
    assert "Search settings" in summary
    assert "[@m2]" in summary


def test_compress_screencap_empty_or_small() -> None:
    assert compress_screencap_bytes(b"") == b""
    assert compress_screencap_bytes(b"short") == b"short"


@pytest.mark.asyncio
async def test_android_backend_actions() -> None:
    backend = AndroidAdbBackend(host="192.168.1.100", port=5555)
    with patch.object(backend.client, "run_adb", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (0, "Success", "")

        tap_res = await backend.tap(500, 600)
        assert tap_res.success is True
        assert "500, 600" in tap_res.message

        swipe_res = await backend.swipe(100, 200, 100, 800)
        assert swipe_res.success is True

        key_res = await backend.key("back")
        assert key_res.success is True
        assert "KEYCODE_BACK" in key_res.message

        launch_res = await backend.launch_app("settings")
        assert launch_res.success is True
