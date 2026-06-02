import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.processors.normalize_processor import (
    NormalizeProcessor,
    normalize_content,
)


def test_normalize_content_basic():
    """Test basic normalization rules."""
    # 1. CRLF to LF
    assert normalize_content("hello\r\nworld\r") == "hello\nworld"

    # 2. Zero-width characters
    assert normalize_content("hello\u200bworld\u200c") == "helloworld"

    # 3. Multiple newlines compression
    assert normalize_content("hello\n\n\nworld") == "hello\n\nworld"
    assert normalize_content("hello\n  \n \nworld") == "hello\n\nworld"

    # 4. Strip whitespace
    assert normalize_content("  hello world  \n") == "hello world"


@pytest.mark.asyncio
async def test_normalize_processor_string_content():
    """Test NormalizeProcessor with string content messages."""
    processor = NormalizeProcessor()

    messages = [
        SystemMessage(content="System\r\nPrompt\n\n\n\nEnd"),
        HumanMessage(content="\u200bHello\n \n \nWorld  "),
    ]

    context = ProcessorContext(messages=messages, user_query="")

    assert await processor.should_process(context) is True

    processed_context = await processor.process(context)

    assert processed_context.messages[0].content == "System\nPrompt\n\nEnd"
    assert processed_context.messages[1].content == "Hello\n\nWorld"


@pytest.mark.asyncio
async def test_normalize_processor_multimodal_content():
    """Test NormalizeProcessor with multimodal/list content."""
    processor = NormalizeProcessor()

    messages = [
        HumanMessage(content=[
            {"type": "text", "text": "Text\r\n\r\n\r\nPart  "},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}},
            {"type": "text", "text": "More\u200bText"},
        ])
    ]

    context = ProcessorContext(messages=messages, user_query="")
    processed_context = await processor.process(context)

    content = processed_context.messages[0].content
    assert content[0]["text"] == "Text\n\nPart"
    assert content[1]["type"] == "image_url"  # Unchanged
    assert content[2]["text"] == "MoreText"
