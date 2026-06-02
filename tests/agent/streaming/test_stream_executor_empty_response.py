import asyncio
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from myrm_agent_harness.agent.streaming.stream_executor import StreamContext, StreamExecutor
from myrm_agent_harness.agent.types import AgentRunStatistics
from myrm_agent_harness.toolkits.llms.errors import MyrmLLMError
from myrm_agent_harness.toolkits.llms.errors.error_types import FailoverReason


class DummyCompactor:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def put(self, event: object) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        pass


@pytest.fixture
def mock_context():
    stats = AgentRunStatistics()
    ctx = StreamContext(
        agent=None,
        agent_input={"messages": []},
        merged_context={"locale": "en"},
        run_config={},
        stats=stats,
        message_id="test_msg_id",
        cancel_token=None,
        steering_token=None,
        source_tracker=MagicMock(),
        output_queue=asyncio.Queue(),
    )
    return ctx


def _make_executor(ctx: StreamContext) -> StreamExecutor:
    executor = StreamExecutor(ctx=ctx, fallback_llm=None, rebuild_agent_fn=None, safety_fallback_llm=None)
    executor._compactor = DummyCompactor()
    return executor


@pytest.mark.asyncio
async def test_empty_response_detected(mock_context):
    """When LLM returns empty string and no tool calls, it should inject recovery prompt."""
    executor = _make_executor(mock_context)

    msg = AIMessage(content="")
    collected_messages = [msg]

    result = await executor._handle_empty_response(collected_messages, retries=0)

    assert result is True
    assert not executor.streaming_final_answer

    # Check if recovery prompt was injected
    messages = mock_context.agent_input["messages"]
    assert len(messages) == 2
    assert messages[0] == msg
    assert isinstance(messages[1], HumanMessage)
    assert "Your response was completely empty" in messages[1].content


@pytest.mark.asyncio
async def test_empty_response_with_thinking_only(mock_context):
    """When LLM returns ONLY thinking blocks and no tool calls, it should still inject recovery prompt."""
    executor = _make_executor(mock_context)

    # Simulate Claude 3.7 thinking block
    msg = AIMessage(content=[{"type": "thinking", "thinking": "Let me think..."}])
    collected_messages = [msg]

    result = await executor._handle_empty_response(collected_messages, retries=0)

    assert result is True
    assert not executor.streaming_final_answer

    # Check if recovery prompt was injected
    messages = mock_context.agent_input["messages"]
    assert len(messages) == 2
    assert isinstance(messages[1], HumanMessage)
    assert "Your response was completely empty" in messages[1].content


@pytest.mark.asyncio
async def test_not_empty_with_content(mock_context):
    """When LLM returns actual content, it should return False."""
    executor = _make_executor(mock_context)

    msg = AIMessage(content="Here is the answer.")
    collected_messages = [msg]

    result = await executor._handle_empty_response(collected_messages, retries=0)

    assert result is False


@pytest.mark.asyncio
async def test_not_empty_with_tool_calls(mock_context):
    """When LLM returns tool calls, it should return False."""
    executor = _make_executor(mock_context)

    msg = AIMessage(content="", tool_calls=[{"name": "search", "args": {}, "id": "call_1"}])
    collected_messages = [msg]

    result = await executor._handle_empty_response(collected_messages, retries=0)

    assert result is False


@pytest.mark.asyncio
async def test_empty_response_exhausted(mock_context):
    """When empty response retries are exhausted, it should raise MyrmLLMError."""
    executor = _make_executor(mock_context)

    msg = AIMessage(content="")
    collected_messages = [msg]

    with pytest.raises(MyrmLLMError) as exc_info:
        await executor._handle_empty_response(collected_messages, retries=2)

    assert exc_info.value.error_code == FailoverReason.FORMAT_ERROR
    assert "empty response repeatedly" in exc_info.value.default_msg


@pytest.mark.asyncio
async def test_empty_response_resume_mode(mock_context):
    """In resume mode, empty response recovery is not supported."""
    mock_context.agent_input = Command(resume="some_value")
    executor = _make_executor(mock_context)

    msg = AIMessage(content="")
    collected_messages = [msg]

    result = await executor._handle_empty_response(collected_messages, retries=0)

    assert result is False
