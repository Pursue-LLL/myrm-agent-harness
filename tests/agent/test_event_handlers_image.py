"""Unit tests for TOOL_IMAGE_OUTPUT event handling in event_handlers.

Covers base64 and URL image emission from multimodal ToolMessage content blocks.
"""

import pytest
from langchain_core.messages import ToolMessage

from myrm_agent_harness.agent.streaming.event_handlers import process_updates_chunk
from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.agent.types import AgentRunStatistics


def _make_tool_msg(content: list[dict[str, str]], name: str = "screenshot_tool") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id="tc_001", name=name)


def _wrap_in_updates(msg: ToolMessage) -> dict[str, dict[str, object]]:
    return {"agent": {"messages": [msg]}}


@pytest.mark.asyncio
async def test_base64_image_emits_tool_image_output():
    msg = _make_tool_msg([{"type": "image", "base64": "iVBORw0KGgo=", "mime_type": "image/png"}])
    data = _wrap_in_updates(msg)
    stats = AgentRunStatistics()
    events = [e async for e in process_updates_chunk(data, stats, "msg_001")]

    image_events = [e for e in events if e["type"] == AgentEventType.TOOL_IMAGE_OUTPUT.value]
    assert len(image_events) == 1
    assert image_events[0]["data"]["base64"] == "iVBORw0KGgo="
    assert image_events[0]["data"]["mime_type"] == "image/png"
    assert image_events[0]["tool_name"] == "screenshot_tool"


@pytest.mark.asyncio
async def test_url_image_emits_tool_image_output():
    msg = _make_tool_msg([{"type": "image", "url": "https://example.com/img.png", "mime_type": "image/png"}])
    data = _wrap_in_updates(msg)
    stats = AgentRunStatistics()
    events = [e async for e in process_updates_chunk(data, stats, "msg_001")]

    image_events = [e for e in events if e["type"] == AgentEventType.TOOL_IMAGE_OUTPUT.value]
    assert len(image_events) == 1
    assert image_events[0]["data"]["url"] == "https://example.com/img.png"
    assert image_events[0]["data"]["mime_type"] == "image/png"
    assert "base64" not in image_events[0]["data"]


@pytest.mark.asyncio
async def test_url_image_default_mime_type():
    msg = _make_tool_msg([{"type": "image", "url": "https://example.com/img.png"}])
    data = _wrap_in_updates(msg)
    stats = AgentRunStatistics()
    events = [e async for e in process_updates_chunk(data, stats, "msg_001")]

    image_events = [e for e in events if e["type"] == AgentEventType.TOOL_IMAGE_OUTPUT.value]
    assert len(image_events) == 1
    assert image_events[0]["data"]["mime_type"] == "image/png"


@pytest.mark.asyncio
async def test_base64_image_default_mime_type():
    msg = _make_tool_msg([{"type": "image", "base64": "abc123"}])
    data = _wrap_in_updates(msg)
    stats = AgentRunStatistics()
    events = [e async for e in process_updates_chunk(data, stats, "msg_001")]

    image_events = [e for e in events if e["type"] == AgentEventType.TOOL_IMAGE_OUTPUT.value]
    assert len(image_events) == 1
    assert image_events[0]["data"]["mime_type"] == "image/jpeg"


@pytest.mark.asyncio
async def test_mixed_base64_and_url_images():
    msg = _make_tool_msg([
        {"type": "image", "base64": "b64data", "mime_type": "image/jpeg"},
        {"type": "image", "url": "https://cdn.example.com/photo.jpg", "mime_type": "image/jpeg"},
    ])
    data = _wrap_in_updates(msg)
    stats = AgentRunStatistics()
    events = [e async for e in process_updates_chunk(data, stats, "msg_001")]

    image_events = [e for e in events if e["type"] == AgentEventType.TOOL_IMAGE_OUTPUT.value]
    assert len(image_events) == 2
    assert image_events[0]["data"]["base64"] == "b64data"
    assert image_events[1]["data"]["url"] == "https://cdn.example.com/photo.jpg"


@pytest.mark.asyncio
async def test_image_block_without_base64_or_url_is_ignored():
    msg = _make_tool_msg([{"type": "image"}])
    data = _wrap_in_updates(msg)
    stats = AgentRunStatistics()
    events = [e async for e in process_updates_chunk(data, stats, "msg_001")]

    image_events = [e for e in events if e["type"] == AgentEventType.TOOL_IMAGE_OUTPUT.value]
    assert len(image_events) == 0


@pytest.mark.asyncio
async def test_non_image_blocks_do_not_emit_image_events():
    msg = _make_tool_msg([
        {"type": "text", "text": "hello"},
        {"type": "image", "base64": "data123", "mime_type": "image/png"},
    ])
    data = _wrap_in_updates(msg)
    stats = AgentRunStatistics()
    events = [e async for e in process_updates_chunk(data, stats, "msg_001")]

    image_events = [e for e in events if e["type"] == AgentEventType.TOOL_IMAGE_OUTPUT.value]
    assert len(image_events) == 1


@pytest.mark.asyncio
async def test_string_content_tool_message_no_image_events():
    msg = ToolMessage(content="plain text result", tool_call_id="tc_005", name="text_tool")
    data = _wrap_in_updates(msg)
    stats = AgentRunStatistics()
    events = [e async for e in process_updates_chunk(data, stats, "msg_005")]

    image_events = [e for e in events if e["type"] == AgentEventType.TOOL_IMAGE_OUTPUT.value]
    assert len(image_events) == 0


@pytest.mark.asyncio
async def test_error_tool_message_no_image_events():
    msg = ToolMessage(content="Tool failed", tool_call_id="tc_006", name="failing_tool", status="error")
    data = _wrap_in_updates(msg)
    stats = AgentRunStatistics()
    events = [e async for e in process_updates_chunk(data, stats, "msg_006")]

    image_events = [e for e in events if e["type"] == AgentEventType.TOOL_IMAGE_OUTPUT.value]
    assert len(image_events) == 0
    error_events = [e for e in events if "error" in str(e.get("step_key", ""))]
    assert len(error_events) == 1


@pytest.mark.asyncio
async def test_empty_list_content_no_image_events():
    msg = ToolMessage(content=[], tool_call_id="tc_007", name="empty_tool")
    data = _wrap_in_updates(msg)
    stats = AgentRunStatistics()
    events = [e async for e in process_updates_chunk(data, stats, "msg_007")]

    image_events = [e for e in events if e["type"] == AgentEventType.TOOL_IMAGE_OUTPUT.value]
    assert len(image_events) == 0


@pytest.mark.asyncio
async def test_message_id_propagated_to_image_event():
    msg = _make_tool_msg([{"type": "image", "url": "https://example.com/img.png"}])
    data = _wrap_in_updates(msg)
    stats = AgentRunStatistics()
    events = [e async for e in process_updates_chunk(data, stats, "custom-msg-id-42")]

    image_events = [e for e in events if e["type"] == AgentEventType.TOOL_IMAGE_OUTPUT.value]
    assert len(image_events) == 1
    assert image_events[0]["messageId"] == "custom-msg-id-42"
