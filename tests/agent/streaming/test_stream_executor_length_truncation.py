import asyncio
import contextlib
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.agent.streaming.stream_executor import StreamContext, StreamExecutor
from myrm_agent_harness.agent.types import AgentRunStatistics


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
        agent_input={},
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
async def test_thinking_budget_exhausted_detected(mock_context):
    """When finish_reason=length + reasoning only + no tool_calls → thinking_budget_exhausted."""
    executor = _make_executor(mock_context)

    ai_msg = AIMessage(
        content="",
        additional_kwargs={"reasoning_content": "Long reasoning chain that consumed all tokens..."},
    )
    collected_messages = [ai_msg]

    tracker_mock = MagicMock()
    tracker_mock.last_finish_reason = "length"

    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=tracker_mock,
    ):
        await executor._handle_length_truncation(collected_messages)

    events = executor._compactor.events
    assert len(events) == 1
    assert events[0]["step_key"] == "thinking_budget_exhausted"
    assert events[0]["messageId"] == "test_msg_id"
    assert "diagnostic_result" in events[0]
    assert events[0]["diagnostic_result"]["error_type"] == "thinking_budget_exhausted"


@pytest.mark.asyncio
async def test_tool_call_truncated_triggers_retry(mock_context):
    """When finish_reason=length + has tool_calls → auto-retry (first time)."""
    mock_context.agent_input = {"messages": []}
    executor = _make_executor(mock_context)

    ai_msg = AIMessage(
        content="",
        tool_calls=[{"name": "write_file", "args": {"path": "test.py", "content": "truncat"}, "id": "call_1"}],
    )
    collected_messages = [ai_msg]

    tracker_mock = MagicMock()
    tracker_mock.last_finish_reason = "length"

    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=tracker_mock,
    ):
        result = await executor._handle_length_truncation(collected_messages)

    assert result is True
    events = executor._compactor.events
    assert len(events) == 1
    assert events[0]["step_key"] == "tool_call_retry"


@pytest.mark.asyncio
async def test_tool_call_truncated_exhausted_after_retry(mock_context):
    """After 1 retry, tool_call_truncated warning is emitted."""
    mock_context.agent_input = {"messages": []}
    executor = _make_executor(mock_context)
    executor._tool_truncation_retries = 1

    ai_msg = AIMessage(
        content="",
        tool_calls=[{"name": "write_file", "args": {"path": "test.py", "content": "truncat"}, "id": "call_1"}],
    )
    collected_messages = [ai_msg]

    tracker_mock = MagicMock()
    tracker_mock.last_finish_reason = "length"

    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=tracker_mock,
    ):
        result = await executor._handle_length_truncation(collected_messages)

    assert result is False
    events = executor._compactor.events
    assert len(events) == 1
    assert events[0]["step_key"] == "tool_call_truncated"


@pytest.mark.asyncio
async def test_no_truncation_when_finish_reason_stop(mock_context):
    """When finish_reason=stop → no truncation event emitted."""
    executor = _make_executor(mock_context)

    ai_msg = AIMessage(content="Normal response")
    collected_messages = [ai_msg]

    tracker_mock = MagicMock()
    tracker_mock.last_finish_reason = "stop"

    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=tracker_mock,
    ):
        await executor._handle_length_truncation(collected_messages)

    assert len(executor._compactor.events) == 0


@pytest.mark.asyncio
async def test_no_truncation_when_no_tracker(mock_context):
    """When no tracker available → no truncation event."""
    executor = _make_executor(mock_context)

    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=None,
    ):
        await executor._handle_length_truncation([])

    assert len(executor._compactor.events) == 0


@pytest.mark.asyncio
async def test_text_continuation_for_normal_text_truncation(mock_context):
    """When finish_reason=length + normal text content + no tool_calls → auto-continue with text_continuation event."""
    mock_context.agent_input = {"messages": []}
    executor = _make_executor(mock_context)

    ai_msg = AIMessage(content="Some normal text that got truncated...")
    collected_messages = [ai_msg]

    tracker_mock = MagicMock()
    tracker_mock.last_finish_reason = "length"

    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=tracker_mock,
    ):
        result = await executor._handle_length_truncation(collected_messages)

    assert result is True
    assert len(executor._compactor.events) == 1
    assert executor._compactor.events[0]["step_key"] == "text_continuation"


@pytest.mark.asyncio
async def test_max_tokens_finish_reason(mock_context):
    """max_tokens finish reason should also trigger detection (Anthropic)."""
    executor = _make_executor(mock_context)

    ai_msg = AIMessage(
        content="",
        additional_kwargs={"reasoning_content": "Anthropic thinking block..."},
    )
    collected_messages = [ai_msg]

    tracker_mock = MagicMock()
    tracker_mock.last_finish_reason = "max_tokens"

    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=tracker_mock,
    ):
        await executor._handle_length_truncation(collected_messages)

    events = executor._compactor.events
    assert len(events) == 1
    assert events[0]["step_key"] == "thinking_budget_exhausted"


@pytest.mark.asyncio
async def test_anthropic_thinking_block_detection(mock_context):
    """Anthropic-style thinking blocks (content list with type=thinking) should be detected."""
    executor = _make_executor(mock_context)

    ai_msg = AIMessage(
        content=[{"type": "thinking", "thinking": "Deep reasoning..."}],
    )
    collected_messages = [ai_msg]

    tracker_mock = MagicMock()
    tracker_mock.last_finish_reason = "max_tokens"

    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=tracker_mock,
    ):
        await executor._handle_length_truncation(collected_messages)

    events = executor._compactor.events
    assert len(events) == 1
    assert events[0]["step_key"] == "thinking_budget_exhausted"


@pytest.mark.asyncio
async def test_locale_propagation(mock_context):
    """Diagnostic should use locale from merged_context."""
    mock_context.merged_context = {"locale": "zh-CN"}
    mock_context.agent_input = {"messages": []}
    executor = _make_executor(mock_context)

    ai_msg = AIMessage(
        content="",
        tool_calls=[{"name": "write_file", "args": {"path": "f.py", "content": "c"}, "id": "call_1"}],
    )
    collected_messages = [ai_msg]

    tracker_mock = MagicMock()
    tracker_mock.last_finish_reason = "length"

    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=tracker_mock,
    ):
        result = await executor._handle_length_truncation(collected_messages)

    assert result is True
    events = executor._compactor.events
    assert len(events) == 1
    assert events[0]["diagnostic_result"]["locale"] == "zh-CN"


@pytest.mark.asyncio
async def test_empty_collected_messages(mock_context):
    """No AIMessage in collected_messages → no event."""
    executor = _make_executor(mock_context)

    tracker_mock = MagicMock()
    tracker_mock.last_finish_reason = "length"

    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=tracker_mock,
    ):
        await executor._handle_length_truncation([])

    assert len(executor._compactor.events) == 0


@pytest.mark.asyncio
async def test_only_human_messages(mock_context):
    """Only HumanMessage in collected_messages → no event."""
    from langchain_core.messages import HumanMessage

    executor = _make_executor(mock_context)

    collected_messages = [HumanMessage(content="Hello")]

    tracker_mock = MagicMock()
    tracker_mock.last_finish_reason = "length"

    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=tracker_mock,
    ):
        await executor._handle_length_truncation(collected_messages)

    assert len(executor._compactor.events) == 0


@pytest.mark.asyncio
async def test_tool_calls_with_reasoning_prioritizes_tool_call(mock_context):
    """When both tool_calls and reasoning present, should trigger tool-call retry."""
    mock_context.agent_input = {"messages": []}
    executor = _make_executor(mock_context)

    ai_msg = AIMessage(
        content="",
        additional_kwargs={"reasoning_content": "Some reasoning..."},
        tool_calls=[{"name": "write_file", "args": {"path": "f.py", "content": "c"}, "id": "call_1"}],
    )
    collected_messages = [ai_msg]

    tracker_mock = MagicMock()
    tracker_mock.last_finish_reason = "length"

    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=tracker_mock,
    ):
        result = await executor._handle_length_truncation(collected_messages)

    assert result is True
    events = executor._compactor.events
    assert len(events) == 1
    assert events[0]["step_key"] == "tool_call_retry"


@pytest.mark.asyncio
async def test_tool_calls_with_content(mock_context):
    """tool_calls + regular content + length → tool-call retry (tool_calls take priority)."""
    mock_context.agent_input = {"messages": []}
    executor = _make_executor(mock_context)

    ai_msg = AIMessage(
        content="Let me write the file for you.",
        tool_calls=[{"name": "write_file", "args": {"path": "f.py", "content": "..."}, "id": "call_1"}],
    )
    collected_messages = [ai_msg]

    tracker_mock = MagicMock()
    tracker_mock.last_finish_reason = "length"

    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=tracker_mock,
    ):
        result = await executor._handle_length_truncation(collected_messages)

    assert result is True
    events = executor._compactor.events
    assert len(events) == 1
    assert events[0]["step_key"] == "tool_call_retry"


@pytest.mark.asyncio
async def test_merged_context_none(mock_context):
    """merged_context=None → defaults to locale 'en'."""
    mock_context.merged_context = None
    mock_context.agent_input = {"messages": []}
    executor = _make_executor(mock_context)

    ai_msg = AIMessage(
        content="",
        tool_calls=[{"name": "bash", "args": {"command": "ls"}, "id": "call_1"}],
    )
    collected_messages = [ai_msg]

    tracker_mock = MagicMock()
    tracker_mock.last_finish_reason = "length"

    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=tracker_mock,
    ):
        result = await executor._handle_length_truncation(collected_messages)

    assert result is True
    events = executor._compactor.events
    assert len(events) == 1
    assert events[0]["diagnostic_result"]["locale"] == "en"


@pytest.mark.asyncio
async def test_picks_last_ai_message(mock_context):
    """Should use the LAST AIMessage, not the first."""
    from langchain_core.messages import HumanMessage

    mock_context.agent_input = {"messages": []}
    executor = _make_executor(mock_context)

    first_ai = AIMessage(content="First response")
    human = HumanMessage(content="Continue")
    last_ai = AIMessage(
        content="",
        tool_calls=[{"name": "write_file", "args": {"path": "f.py", "content": "..."}, "id": "call_1"}],
    )
    collected_messages = [first_ai, human, last_ai]

    tracker_mock = MagicMock()
    tracker_mock.last_finish_reason = "length"

    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=tracker_mock,
    ):
        result = await executor._handle_length_truncation(collected_messages)

    assert result is True
    events = executor._compactor.events
    assert len(events) == 1
    assert events[0]["step_key"] == "tool_call_retry"


@pytest.mark.asyncio
async def test_diagnostic_failure_still_emits_event(mock_context):
    """If diagnostic generation fails, event is still emitted without diagnostic_result."""
    mock_context.agent_input = {"messages": []}
    executor = _make_executor(mock_context)
    executor._tool_truncation_retries = 1

    ai_msg = AIMessage(
        content="",
        tool_calls=[{"name": "write_file", "args": {"path": "f.py", "content": "..."}, "id": "call_1"}],
    )
    collected_messages = [ai_msg]

    tracker_mock = MagicMock()
    tracker_mock.last_finish_reason = "length"

    with (
        patch(
            "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
            return_value=tracker_mock,
        ),
        patch(
            "myrm_agent_harness.agent.errors.diagnostics.LLMErrorDiagnostic.diagnose_truncation",
            side_effect=Exception("i18n module broken"),
        ),
    ):
        result = await executor._handle_length_truncation(collected_messages)

    assert result is False
    events = executor._compactor.events
    assert len(events) == 1
    assert events[0]["step_key"] == "tool_call_truncated"
    assert "diagnostic_result" not in events[0]


# ---------------------------------------------------------------------------
# ContextVar accessors
# ---------------------------------------------------------------------------


def test_contextvar_get_set_reset():
    """get/set/reset ephemeral_max_output_tokens ContextVar round-trip."""
    from myrm_agent_harness.agent.streaming.stream_recovery_truncation import (
        get_ephemeral_max_output_tokens,
        reset_ephemeral_max_output_tokens,
        set_ephemeral_max_output_tokens,
    )

    assert get_ephemeral_max_output_tokens() is None

    set_ephemeral_max_output_tokens(8000)
    assert get_ephemeral_max_output_tokens() == 8000

    reset_ephemeral_max_output_tokens()
    assert get_ephemeral_max_output_tokens() is None


def test_contextvar_set_caps_at_max():
    """set_ephemeral_max_output_tokens caps at _MAX_EPHEMERAL_OUTPUT_TOKENS (32768)."""
    from myrm_agent_harness.agent.streaming.stream_recovery_truncation import (
        _MAX_EPHEMERAL_OUTPUT_TOKENS,
        get_ephemeral_max_output_tokens,
        reset_ephemeral_max_output_tokens,
        set_ephemeral_max_output_tokens,
    )

    set_ephemeral_max_output_tokens(999999)
    assert get_ephemeral_max_output_tokens() == _MAX_EPHEMERAL_OUTPUT_TOKENS
    reset_ephemeral_max_output_tokens()


# ---------------------------------------------------------------------------
# Text continuation exhausted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_text_continuation_exhausted(mock_context):
    """When retries >= _MAX_LENGTH_CONTINUE_RETRIES → text_continuation_exhausted."""
    mock_context.agent_input = {"messages": []}
    executor = _make_executor(mock_context)

    ai_msg = AIMessage(content="Some text that keeps getting truncated...")
    collected_messages = [ai_msg]

    tracker_mock = MagicMock()
    tracker_mock.last_finish_reason = "length"

    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=tracker_mock,
    ):
        result = await executor._handle_length_truncation(collected_messages, retries=3)

    assert result is False
    events = executor._compactor.events
    assert len(events) == 1
    assert events[0]["step_key"] == "text_continuation_exhausted"


# ---------------------------------------------------------------------------
# Command (Resume) mode — text continuation not supported
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_text_continuation_skipped_in_command_mode(mock_context):
    """In Command/Resume mode, text continuation returns False without event."""
    from langgraph.types import Command

    mock_context.agent_input = Command(resume="resumed")
    executor = _make_executor(mock_context)

    ai_msg = AIMessage(content="Truncated text in resume...")
    collected_messages = [ai_msg]

    tracker_mock = MagicMock()
    tracker_mock.last_finish_reason = "length"

    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=tracker_mock,
    ):
        result = await executor._handle_length_truncation(collected_messages)

    assert result is False
    assert len(executor._compactor.events) == 0


# ---------------------------------------------------------------------------
# Command (Resume) mode — tool-call retry not supported
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_call_retry_skipped_in_command_mode(mock_context):
    """In Command/Resume mode, tool-call retry emits tool_call_truncated and returns False."""
    from langgraph.types import Command

    mock_context.agent_input = Command(resume="resumed")
    executor = _make_executor(mock_context)

    ai_msg = AIMessage(
        content="",
        tool_calls=[{"name": "write_file", "args": {"path": "f.py", "content": "c"}, "id": "call_1"}],
    )
    collected_messages = [ai_msg]

    tracker_mock = MagicMock()
    tracker_mock.last_finish_reason = "length"

    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=tracker_mock,
    ):
        result = await executor._handle_length_truncation(collected_messages)

    assert result is False
    events = executor._compactor.events
    assert len(events) == 1
    assert events[0]["step_key"] == "tool_call_truncated"


# ---------------------------------------------------------------------------
# _boost_output_tokens with valid LLM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_boost_output_tokens_progressive_scaling(mock_context):
    """_boost_output_tokens applies progressive scaling: 2x, 3x, 4x."""
    from myrm_agent_harness.agent.streaming.stream_recovery_truncation import (
        get_ephemeral_max_output_tokens,
        reset_ephemeral_max_output_tokens,
    )

    llm_mock = MagicMock()
    llm_mock.max_tokens = 4000
    mock_context.llm = llm_mock
    executor = _make_executor(mock_context)

    executor._boost_output_tokens(0)
    assert get_ephemeral_max_output_tokens() == 8000

    executor._boost_output_tokens(1)
    assert get_ephemeral_max_output_tokens() == 12000

    executor._boost_output_tokens(2)
    assert get_ephemeral_max_output_tokens() == 16000

    executor._boost_output_tokens(5)
    assert get_ephemeral_max_output_tokens() == 16000

    reset_ephemeral_max_output_tokens()


# ---------------------------------------------------------------------------
# _boost_output_tokens with no LLM / no max_tokens
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_boost_no_op_when_llm_is_none(mock_context):
    """_boost_output_tokens is a no-op when llm is None."""
    from myrm_agent_harness.agent.streaming.stream_recovery_truncation import (
        get_ephemeral_max_output_tokens,
    )

    mock_context.llm = None
    executor = _make_executor(mock_context)

    executor._boost_output_tokens(0)
    assert get_ephemeral_max_output_tokens() is None


@pytest.mark.asyncio
async def test_boost_no_op_when_max_tokens_invalid(mock_context):
    """_boost_output_tokens is a no-op when max_tokens is 0 or negative."""
    from myrm_agent_harness.agent.streaming.stream_recovery_truncation import (
        get_ephemeral_max_output_tokens,
    )

    llm_mock = MagicMock()
    llm_mock.max_tokens = 0
    mock_context.llm = llm_mock
    executor = _make_executor(mock_context)

    executor._boost_output_tokens(0)
    assert get_ephemeral_max_output_tokens() is None

    llm_mock.max_tokens = -1
    executor._boost_output_tokens(0)
    assert get_ephemeral_max_output_tokens() is None


# ---------------------------------------------------------------------------
# Edge: no content, no reasoning, no tool_calls → early return False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_content_no_reasoning_no_tool_calls(mock_context):
    """AIMessage with empty content and no tool_calls → returns False, no event."""
    executor = _make_executor(mock_context)

    ai_msg = AIMessage(content="")
    collected_messages = [ai_msg]

    tracker_mock = MagicMock()
    tracker_mock.last_finish_reason = "length"

    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=tracker_mock,
    ):
        result = await executor._handle_length_truncation(collected_messages)

    assert result is False
    assert len(executor._compactor.events) == 0


# ---------------------------------------------------------------------------
# _has_non_reasoning_content: list content with string items
# ---------------------------------------------------------------------------


def test_has_non_reasoning_content_list_with_strings():
    """_has_non_reasoning_content returns True for list content with non-empty strings."""
    from myrm_agent_harness.agent.streaming.stream_recovery_truncation import StreamTruncationRecoveryMixin

    msg = MagicMock()
    msg.content = ["hello", "world"]
    assert StreamTruncationRecoveryMixin._has_non_reasoning_content(msg) is True

    msg.content = ["", "  "]
    assert StreamTruncationRecoveryMixin._has_non_reasoning_content(msg) is False


def test_has_non_reasoning_content_list_with_non_thinking_dict():
    """_has_non_reasoning_content returns True for non-thinking dict blocks."""
    from myrm_agent_harness.agent.streaming.stream_recovery_truncation import StreamTruncationRecoveryMixin

    msg = MagicMock()
    msg.content = [{"type": "text", "text": "visible"}]
    assert StreamTruncationRecoveryMixin._has_non_reasoning_content(msg) is True

    msg.content = [{"type": "thinking", "thinking": "internal"}]
    assert StreamTruncationRecoveryMixin._has_non_reasoning_content(msg) is False


# ---------------------------------------------------------------------------
# Text continuation: message list correctness + streaming_final_answer reset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_text_continuation_injects_prompt_and_resets_flag(mock_context):
    """Text continuation appends continuation prompt and resets streaming_final_answer."""
    from langchain_core.messages import HumanMessage

    mock_context.agent_input = {"messages": []}
    executor = _make_executor(mock_context)
    executor.streaming_final_answer = True

    ai_msg = AIMessage(content="Truncated text content...")
    collected_messages = [ai_msg]

    tracker_mock = MagicMock()
    tracker_mock.last_finish_reason = "length"

    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=tracker_mock,
    ):
        result = await executor._handle_length_truncation(collected_messages)

    assert result is True
    assert executor.streaming_final_answer is False

    messages = mock_context.agent_input["messages"]
    assert len(messages) == 2
    assert messages[0] is ai_msg
    assert isinstance(messages[1], HumanMessage)
    assert "truncated" in messages[1].content.lower()


# ---------------------------------------------------------------------------
# Tool-call retry: message cleanup correctness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_call_retry_drops_truncated_ai_message(mock_context):
    """Tool-call retry drops the truncated AI message and appends a retry hint."""
    from langchain_core.messages import HumanMessage

    mock_context.agent_input = {"messages": []}
    executor = _make_executor(mock_context)
    executor.streaming_final_answer = True

    human_msg = HumanMessage(content="Write a file")
    ai_msg = AIMessage(
        content="",
        tool_calls=[{"name": "write_file", "args": {"path": "f.py", "content": "..."}, "id": "call_1"}],
    )
    collected_messages = [human_msg, ai_msg]

    tracker_mock = MagicMock()
    tracker_mock.last_finish_reason = "length"

    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=tracker_mock,
    ):
        result = await executor._handle_length_truncation(collected_messages)

    assert result is True
    assert executor.streaming_final_answer is False

    messages = mock_context.agent_input["messages"]
    assert len(messages) == 2
    assert messages[0] is human_msg
    assert isinstance(messages[1], HumanMessage)
    assert "truncated" in messages[1].content.lower()
    assert executor._tool_truncation_retries == 1


# ---------------------------------------------------------------------------
# ContextVar cleanup in StreamExecutor finally block
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ephemeral_contextvar_reset_after_execute():
    """ContextVar is always reset in StreamExecutor.execute's finally block."""
    from myrm_agent_harness.agent.streaming.stream_recovery_truncation import (
        get_ephemeral_max_output_tokens,
        set_ephemeral_max_output_tokens,
    )

    set_ephemeral_max_output_tokens(16000)
    assert get_ephemeral_max_output_tokens() == 16000

    stats = AgentRunStatistics()
    ctx = StreamContext(
        agent=MagicMock(),
        agent_input={"messages": []},
        merged_context={},
        run_config={},
        stats=stats,
        message_id="test",
        cancel_token=None,
        steering_token=None,
        source_tracker=MagicMock(),
        output_queue=asyncio.Queue(),
    )
    executor = _make_executor(ctx)

    ctx.agent.astream_events = MagicMock(side_effect=RuntimeError("test abort"))

    with contextlib.suppress(RuntimeError):
        await executor.execute()

    assert get_ephemeral_max_output_tokens() is None


# ---------------------------------------------------------------------------
# Boost cap: ensure 32768 ceiling even with large base
# ---------------------------------------------------------------------------


def test_boost_caps_at_32768():
    """_boost_output_tokens never exceeds _MAX_EPHEMERAL_OUTPUT_TOKENS (32768)."""
    from myrm_agent_harness.agent.streaming.stream_recovery_truncation import (
        get_ephemeral_max_output_tokens,
        reset_ephemeral_max_output_tokens,
    )

    stats = AgentRunStatistics()
    ctx = StreamContext(
        agent=None,
        agent_input={},
        merged_context={},
        run_config={},
        stats=stats,
        message_id="test",
        cancel_token=None,
        steering_token=None,
        source_tracker=MagicMock(),
        output_queue=asyncio.Queue(),
    )

    llm_mock = MagicMock()
    llm_mock.max_tokens = 16384
    ctx.llm = llm_mock

    executor = _make_executor(ctx)
    executor._boost_output_tokens(2)

    val = get_ephemeral_max_output_tokens()
    assert val == 32768
    reset_ephemeral_max_output_tokens()
