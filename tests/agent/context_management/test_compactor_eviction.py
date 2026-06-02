from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from myrm_agent_harness.agent.context_management.infra.schemas import ContextConfig, EvictedToolCall
from myrm_agent_harness.agent.context_management.strategies.compactor import compress_messages_async


@pytest.mark.asyncio
async def test_compress_messages_async_batch_eviction(monkeypatch):
    monkeypatch.setattr("myrm_agent_harness.agent.context_management.strategies.compactor.get_token_count", lambda x: 600)

    mock_compress = AsyncMock(return_value=100)
    monkeypatch.setattr("myrm_agent_harness.agent.context_management.strategies.compactor.compress_tool_message_async", mock_compress)

    ai_msg1 = AIMessage(content="ai1", tool_calls=[{"id": "1", "name": "tool1", "args": {}}])
    tool_msg1 = ToolMessage(content="long tool output 1", tool_call_id="1", name="tool1")

    ai_msg2 = AIMessage(content="ai2", tool_calls=[{"id": "2", "name": "tool2", "args": {}}])
    tool_msg2 = ToolMessage(content="long tool output 2", tool_call_id="2", name="tool2")

    messages = [ai_msg1, tool_msg1, ai_msg2, tool_msg2]

    mock_eviction_cb = AsyncMock()

    _result, _saved = await compress_messages_async(
        messages=messages,
        dynamic_min_save=0,
        config=ContextConfig(max_context_tokens=128000, keep_recent_calls=0),
        on_compress_offload=None,
        on_compress_eviction=mock_eviction_cb,
        user_goal_hint="test goal",
        chat_id="chat1",
        user_id="user1"
    )

    mock_eviction_cb.assert_called_once()
    called_args = mock_eviction_cb.call_args[0]
    evicted_pairs: list[EvictedToolCall] = called_args[0]
    goal_hint = called_args[1]

    assert len(evicted_pairs) == 2
    assert all(isinstance(e, EvictedToolCall) for e in evicted_pairs)

    ai_msgs = [e.ai_msg for e in evicted_pairs]
    tool_msgs = [e.tool_msg for e in evicted_pairs]
    assert ai_msg1 in ai_msgs
    assert ai_msg2 in ai_msgs
    assert tool_msg1 in tool_msgs
    assert tool_msg2 in tool_msgs

    for evicted in evicted_pairs:
        assert isinstance(evicted.original_content, str)
        assert len(evicted.original_content) > 0

    assert goal_hint == "test goal"


@pytest.mark.asyncio
async def test_compress_eviction_preserves_original_content(monkeypatch):
    """Verify that original_content is captured BEFORE compression mutates tool_msg."""
    monkeypatch.setattr("myrm_agent_harness.agent.context_management.strategies.compactor.get_token_count", lambda x: 600)

    original_tool_output = "This is the original long tool output with important data"

    async def mock_compress_fn(tool_msg, ai_msg, **kwargs):
        tool_msg.content = "COMPACTED: tool1 summary"
        return 100

    monkeypatch.setattr(
        "myrm_agent_harness.agent.context_management.strategies.compactor.compress_tool_message_async",
        mock_compress_fn,
    )

    ai_msg = AIMessage(content="ai1", tool_calls=[{"id": "1", "name": "tool1", "args": {}}])
    tool_msg = ToolMessage(content=original_tool_output, tool_call_id="1", name="tool1")

    captured_evictions: list[EvictedToolCall] = []

    async def capture_cb(evicted_pairs: list[EvictedToolCall], user_goal_hint: str) -> None:
        captured_evictions.extend(evicted_pairs)

    await compress_messages_async(
        messages=[ai_msg, tool_msg],
        dynamic_min_save=0,
        config=ContextConfig(max_context_tokens=128000, keep_recent_calls=0),
        on_compress_offload=None,
        on_compress_eviction=capture_cb,
        user_goal_hint="test",
        chat_id="chat1",
        user_id="user1",
    )

    assert len(captured_evictions) == 1
    evicted = captured_evictions[0]
    assert evicted.original_content == original_tool_output
    assert tool_msg.content == "COMPACTED: tool1 summary"

@pytest.mark.asyncio
async def test_compress_messages_async_no_eviction_if_small(monkeypatch):
    # Mock get_token_count to return < 500
    monkeypatch.setattr("myrm_agent_harness.agent.context_management.strategies.compactor.get_token_count", lambda x: 100)

    mock_compress = AsyncMock(return_value=100)
    monkeypatch.setattr("myrm_agent_harness.agent.context_management.strategies.compactor.compress_tool_message_async", mock_compress)

    ai_msg1 = AIMessage(content="ai1", tool_calls=[{"id": "1", "name": "tool1", "args": {}}])
    tool_msg1 = ToolMessage(content="short tool output 1", tool_call_id="1", name="tool1")

    messages = [ai_msg1, tool_msg1]

    mock_eviction_cb = AsyncMock()

    await compress_messages_async(
        messages=messages,
        dynamic_min_save=0,
        config=ContextConfig(max_context_tokens=128000, keep_recent_calls=0),
        on_compress_offload=None,
        on_compress_eviction=mock_eviction_cb,
        user_goal_hint="test goal",
        chat_id="chat1",
        user_id="user1"
    )

    # Eviction callback should NOT be called because tokens < 500
    mock_eviction_cb.assert_not_called()
