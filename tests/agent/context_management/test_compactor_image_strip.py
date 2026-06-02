"""Tests for multimodal image stripping in compress_tool_message_async.

Verifies that base64 image content in ToolMessage is correctly stripped
and flattened to plain text before compression, preventing token waste.
"""

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from myrm_agent_harness.agent.context_management.strategies.compactor import (
    compress_tool_message_async,
)


def _make_tool_pair(
    content: str | list[object],
    tool_name: str = "computer_use",
    tool_call_id: str = "tc_test",
) -> tuple[ToolMessage, AIMessage]:
    tool_msg = ToolMessage(content=content, tool_call_id=tool_call_id, name=tool_name)
    ai_msg = AIMessage(
        content="",
        tool_calls=[{"id": tool_call_id, "name": tool_name, "args": {"action": "screenshot"}}],
    )
    return tool_msg, ai_msg


@pytest.mark.asyncio
async def test_strips_type_image_content() -> None:
    """type='image' (LangChain create_image_block) should be stripped."""
    content: list[object] = [
        {"type": "text", "text": "Screenshot captured after clicking login button"},
        {"type": "image", "base64": "x" * 50000, "mime_type": "image/jpeg"},
    ]
    tool_msg, ai_msg = _make_tool_pair(content)

    await compress_tool_message_async(tool_msg, ai_msg)

    assert isinstance(tool_msg.content, str)
    assert "COMPACTED:" in tool_msg.content
    assert "x" * 100 not in tool_msg.content


@pytest.mark.asyncio
async def test_strips_type_image_url_base64_content() -> None:
    """type='image_url' with base64 data URL should be stripped."""
    content: list[object] = [
        {"type": "text", "text": "User uploaded image analysis"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "A" * 50000}},
    ]
    tool_msg, ai_msg = _make_tool_pair(content)

    await compress_tool_message_async(tool_msg, ai_msg)

    assert isinstance(tool_msg.content, str)
    assert "COMPACTED:" in tool_msg.content
    assert "A" * 100 not in tool_msg.content


@pytest.mark.asyncio
async def test_strips_type_input_image_content() -> None:
    """type='input_image' (Anthropic format) should be stripped."""
    content: list[object] = [
        {"type": "text", "text": "Anthropic image analysis result"},
        {"type": "input_image", "source": {"data": "x" * 50000}},
    ]
    tool_msg, ai_msg = _make_tool_pair(content)

    await compress_tool_message_async(tool_msg, ai_msg)

    assert isinstance(tool_msg.content, str)
    assert "COMPACTED:" in tool_msg.content


@pytest.mark.asyncio
async def test_pure_image_content_stripped() -> None:
    """Content with only images (no text) should still be stripped and compressed."""
    content: list[object] = [
        {"type": "image", "base64": "x" * 50000, "mime_type": "image/jpeg"},
    ]
    tool_msg, ai_msg = _make_tool_pair(content)

    await compress_tool_message_async(tool_msg, ai_msg)

    assert isinstance(tool_msg.content, str)
    assert "COMPACTED:" in tool_msg.content


@pytest.mark.asyncio
async def test_no_image_content_unchanged() -> None:
    """List content without images should be handled normally (json.dumps)."""
    content: list[object] = [
        {"type": "text", "text": "Just text content " * 100},
    ]
    tool_msg, ai_msg = _make_tool_pair(content)

    await compress_tool_message_async(tool_msg, ai_msg)

    assert isinstance(tool_msg.content, str)
    assert "COMPACTED:" in tool_msg.content


@pytest.mark.asyncio
async def test_string_content_unaffected() -> None:
    """Regular string content should not be affected by image stripping."""
    tool_msg, ai_msg = _make_tool_pair("Regular tool output " * 50)

    await compress_tool_message_async(tool_msg, ai_msg)

    assert isinstance(tool_msg.content, str)
    assert "COMPACTED:" in tool_msg.content


@pytest.mark.asyncio
async def test_flatten_preserves_all_text_parts() -> None:
    """After strip, all text parts should be joined with newlines."""
    content: list[object] = [
        {"type": "text", "text": "Step 1: Clicked the button"},
        {"type": "image", "base64": "x" * 50000, "mime_type": "image/jpeg"},
        {"type": "text", "text": "Step 2: Page loaded successfully"},
    ]
    tool_msg, _ai_msg = _make_tool_pair(content)

    original_content = tool_msg.content
    assert isinstance(original_content, list)

    from myrm_agent_harness.utils.image_utils import content_has_images, strip_images_from_content

    assert content_has_images(original_content) is True

    stripped = strip_images_from_content(original_content)
    assert isinstance(stripped, list)
    assert len(stripped) == 3

    text_parts = [item["text"] for item in stripped if isinstance(item, dict) and item.get("type") == "text"]
    assert len(text_parts) == 3
    assert "Step 1" in text_parts[0]
    assert "removed" in text_parts[1].lower()
    assert "Step 2" in text_parts[2]
