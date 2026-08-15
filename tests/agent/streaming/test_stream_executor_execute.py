"""stream_executor.py 的 execute() 主循环集成测试。

覆盖：
- 正常执行流（无异常 → 正常结束）
- Cancel token 触发取消
- overflow 异常 → recovery + continue
- fatal error → _emit_fatal_error → MyrmLLMError
- recovery_actions 注入（api_key / billing / model → 含 actions；unknown → 不含）
- diagnostic 失败时不注入 recovery_actions
- subagent notification → SSE 事件
- steering 注入 → 新轮次
"""

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.agent.streaming.stream_executor import (
    STREAM_DONE,
    StreamContext,
    StreamExecutor,
)
from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.agent.types import AgentRunStatistics


class FakeCompactor:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def put(self, event: object) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        pass


@pytest.fixture
def base_ctx():
    stats = AgentRunStatistics()
    ctx = StreamContext(
        agent=MagicMock(),
        agent_input={"messages": [HumanMessage(content="hello")]},
        merged_context={"locale": "en"},
        run_config={},
        stats=stats,
        message_id="exec_test",
        cancel_token=None,
        steering_token=None,
        source_tracker=MagicMock(),
        output_queue=asyncio.Queue(),
    )
    return ctx


def _make_executor(ctx: StreamContext) -> StreamExecutor:
    executor = StreamExecutor(ctx=ctx, fallback_llm=None, safety_fallback_llm=None, rebuild_agent_fn=MagicMock())
    executor._compactor = FakeCompactor()
    return executor


async def _mock_astream_normal(*args, **kwargs) -> AsyncGenerator:
    yield ("messages", (AIMessage(content="hi"), {"tags": []}))


async def _mock_astream_empty(*args, **kwargs) -> AsyncGenerator:
    return
    yield


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_execute_normal_completes(fire_hook_mock, base_ctx):
    """Normal execution: astream yields events, loop exits normally."""
    executor = _make_executor(base_ctx)
    base_ctx.agent.astream = _mock_astream_normal

    with patch.object(executor, "_dispatch_chunk", new_callable=AsyncMock) as dispatch_mock:
        await executor.execute()

    dispatch_mock.assert_called_once()
    assert executor._compactor.events[-1] is STREAM_DONE


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_execute_cancel_token(fire_hook_mock, base_ctx):
    """Cancel token triggers cancellation event."""
    cancel_token = MagicMock()
    cancel_token.is_cancelled = True
    base_ctx.cancel_token = cancel_token

    executor = _make_executor(base_ctx)
    base_ctx.agent.astream = _mock_astream_normal

    await executor.execute()

    events = executor._compactor.events
    cancel_events = [e for e in events if isinstance(e, dict) and e.get("type") == AgentEventType.CANCELLED.value]
    assert len(cancel_events) == 1
    assert base_ctx.stats.was_cancelled is True


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_execute_overflow_recovery(fire_hook_mock, base_ctx):
    """Overflow exception triggers _handle_overflow → retry."""
    executor = _make_executor(base_ctx)

    call_count = 0

    async def _astream_with_overflow(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("context length exceeded")
        return _mock_astream_empty(*args, **kwargs)

    base_ctx.agent.astream = _astream_with_overflow

    with (
        patch.object(executor, "_handle_overflow", new_callable=AsyncMock, return_value=True) as overflow_mock,
        patch.object(executor, "_dispatch_chunk", new_callable=AsyncMock),
    ):
        # Second call will not raise, but _handle_overflow returns True only once
        overflow_mock.side_effect = [True, False]
        # The exception on second call won't match overflow, so we let it just not raise
        base_ctx.agent.astream = _mock_astream_empty

        # Re-set to raise first time
        original_call = [0]

        async def _astream_raise_once(*args, **kwargs):
            original_call[0] += 1
            if original_call[0] == 1:
                raise Exception("context_length_exceeded")
            async for x in _mock_astream_empty(*args, **kwargs):
                yield x

        base_ctx.agent.astream = _astream_raise_once
        await executor.execute()

    overflow_mock.assert_called_once()


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_execute_fatal_error(fire_hook_mock, base_ctx):
    """Fatal exception that can't be recovered → MyrmLLMError."""
    from myrm_agent_harness.toolkits.llms.errors import MyrmLLMError

    executor = _make_executor(base_ctx)

    async def _astream_fatal(*args, **kwargs):
        raise RuntimeError("unrecoverable error")
        yield

    base_ctx.agent.astream = _astream_fatal

    with pytest.raises(MyrmLLMError):
        await executor.execute()

    events = executor._compactor.events
    error_events = [e for e in events if isinstance(e, dict) and e.get("type") == AgentEventType.ERROR.value]
    assert len(error_events) == 1
    assert "unrecoverable" in str(error_events[0].get("error", ""))


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_emit_fatal_error_with_compression_exhausted(fire_hook_mock, base_ctx):
    """compression_exhausted flag propagates to error event."""
    from myrm_agent_harness.toolkits.llms.errors import MyrmLLMError

    base_ctx.stats.compression_exhausted = True
    executor = _make_executor(base_ctx)

    async def _astream_fatal(*args, **kwargs):
        raise RuntimeError("context overflow final")
        yield

    base_ctx.agent.astream = _astream_fatal

    with pytest.raises(MyrmLLMError):
        await executor.execute()

    error_events = [
        e for e in executor._compactor.events if isinstance(e, dict) and e.get("type") == AgentEventType.ERROR.value
    ]
    assert len(error_events) == 1
    assert error_events[0].get("compression_exhausted") is True


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_emit_fatal_error_with_llm_info(fire_hook_mock, base_ctx):
    """llm_info dict is used for diagnostic context."""
    from myrm_agent_harness.toolkits.llms.errors import MyrmLLMError

    base_ctx.llm_info = {"model_name": "gpt-4o", "base_url": "https://api.openai.com"}
    executor = _make_executor(base_ctx)

    async def _astream_fatal(*args, **kwargs):
        raise RuntimeError("model error")
        yield

    base_ctx.agent.astream = _astream_fatal

    with pytest.raises(MyrmLLMError):
        await executor.execute()

    error_events = [
        e for e in executor._compactor.events if isinstance(e, dict) and e.get("type") == AgentEventType.ERROR.value
    ]
    assert len(error_events) == 1
    assert "diagnostic_result" in error_events[0]
    assert error_events[0].get("fault_side") in {
        "model",
        "harness_tool",
        "harness_pipeline",
        "env",
        "grader",
        "owner",
        "unknown",
    }


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_emit_fatal_error_attributes_env_fault_side(fire_hook_mock, base_ctx):
    """Billing-style fatal errors must be attributed to the environment side."""
    from myrm_agent_harness.toolkits.llms.errors import MyrmLLMError

    executor = _make_executor(base_ctx)

    async def _astream_fatal(*args, **kwargs):
        raise RuntimeError("Insufficient quota for billing")
        yield

    base_ctx.agent.astream = _astream_fatal

    with pytest.raises(MyrmLLMError):
        await executor.execute()

    error_events = [
        e for e in executor._compactor.events if isinstance(e, dict) and e.get("type") == AgentEventType.ERROR.value
    ]
    assert len(error_events) == 1
    assert error_events[0].get("fault_side") == "env"


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_emit_fatal_error_persists_to_event_logger(fire_hook_mock, base_ctx):
    """Fatal errors must be persisted to the event journal so trace
    reconstruction (trace_builder) sees LLM fatal errors."""
    from myrm_agent_harness.toolkits.llms.errors import MyrmLLMError

    event_logger = AsyncMock()
    base_ctx.event_logger = event_logger
    executor = _make_executor(base_ctx)

    async def _astream_fatal(*args, **kwargs):
        raise RuntimeError("Insufficient quota for billing")
        yield

    base_ctx.agent.astream = _astream_fatal

    with pytest.raises(MyrmLLMError):
        await executor.execute()

    event_logger.log.assert_awaited_once()
    call_args = event_logger.log.call_args
    assert call_args.args[0] == "error"
    persisted = call_args.args[1]
    # Transport-only fields stripped before persistence
    assert "type" not in persisted
    assert "messageId" not in persisted
    # Attribution + diagnostics preserved for the post-mortem view
    assert persisted["fault_side"] == "env"
    assert persisted["error_kind"] is not None
    assert persisted["error_type"] == "RuntimeError"


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_emit_fatal_error_no_event_logger_ok(fire_hook_mock, base_ctx):
    """No event_logger configured → fatal error still emitted via compactor."""
    from myrm_agent_harness.toolkits.llms.errors import MyrmLLMError

    executor = _make_executor(base_ctx)

    async def _astream_fatal(*args, **kwargs):
        raise RuntimeError("Insufficient quota for billing")
        yield

    base_ctx.agent.astream = _astream_fatal

    with pytest.raises(MyrmLLMError):
        await executor.execute()

    error_events = [
        e for e in executor._compactor.events if isinstance(e, dict) and e.get("type") == AgentEventType.ERROR.value
    ]
    assert len(error_events) == 1
    assert error_events[0].get("fault_side") == "env"


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
@patch("myrm_agent_harness.agent.errors.diagnostics.LLMErrorDiagnostic")
async def test_emit_fatal_error_diagnostic_failure(diag_mock, fire_hook_mock, base_ctx):
    """Diagnostic generation failure still emits error event (without diagnostic_result)."""
    from myrm_agent_harness.toolkits.llms.errors import MyrmLLMError

    diag_mock.diagnose.side_effect = Exception("diagnostic broken")
    executor = _make_executor(base_ctx)

    async def _astream_fatal(*args, **kwargs):
        raise RuntimeError("diagnostic will fail")
        yield

    base_ctx.agent.astream = _astream_fatal

    with pytest.raises(MyrmLLMError):
        await executor.execute()

    error_events = [
        e for e in executor._compactor.events if isinstance(e, dict) and e.get("type") == AgentEventType.ERROR.value
    ]
    assert len(error_events) == 1
    assert "diagnostic will fail" in str(error_events[0].get("error", ""))
    assert "diagnostic_result" not in error_events[0]


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_execute_steering_injection(fire_hook_mock, base_ctx):
    """Steering token with pending messages triggers new turn."""
    steering_token = MagicMock()
    steering_token.steering_applied = True
    steering_token.has_pending = True
    steering_token.collect_all_steering_messages.return_value = ["Do X instead"]
    base_ctx.steering_token = steering_token

    executor = _make_executor(base_ctx)

    call_count = [0]

    async def _astream_count(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] >= 3:
            steering_token.steering_applied = False
            steering_token.has_pending = False
            steering_token.collect_all_steering_messages.return_value = []
        async for x in _mock_astream_empty(*args, **kwargs):
            yield x

    base_ctx.agent.astream = _astream_count
    await executor.execute()

    assert call_count[0] >= 2


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_execute_redirect_breaks_and_preserves_partial(fire_hook_mock, base_ctx):
    """Redirect breaks astream mid-generation, preserves partial text, and triggers new turn."""
    from myrm_agent_harness.utils.runtime.steering import SteeringToken

    steering_token = SteeringToken()
    base_ctx.steering_token = steering_token

    executor = _make_executor(base_ctx)
    call_count = [0]

    async def _astream_with_redirect(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            yield ("messages", (AIMessage(content="partial answer "), {"langgraph_node": "model"}))
            yield ("messages", (AIMessage(content="more text"), {"langgraph_node": "model"}))
            steering_token.redirect("Actually, do Y instead")
            yield ("messages", (AIMessage(content=" this should not appear"), {"langgraph_node": "model"}))
        else:
            yield ("updates", {"model": {"messages": [AIMessage(content="Final correct answer")]}})

    base_ctx.agent.astream = _astream_with_redirect
    await executor.execute()

    assert call_count[0] == 2
    events = executor._compactor.events
    redirected_events = [e for e in events if isinstance(e, dict) and e.get("type") == AgentEventType.REDIRECTED.value]
    assert len(redirected_events) == 1
    assert redirected_events[0]["data"]["partial_preserved"] is True


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_execute_redirect_partial_buffer_in_messages(fire_hook_mock, base_ctx):
    """Redirect preserves partial text as AIMessage in the context for next turn."""
    from myrm_agent_harness.utils.runtime.steering import SteeringToken

    steering_token = SteeringToken()
    base_ctx.steering_token = steering_token

    executor = _make_executor(base_ctx)
    call_count = [0]

    async def _astream_redirect_scenario(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            yield ("messages", (AIMessage(content="Hello, "), {"langgraph_node": "model"}))
            yield ("messages", (AIMessage(content="I think"), {"langgraph_node": "model"}))
            steering_token.redirect("Wrong direction, do Z")
            yield ("messages", (AIMessage(content=" wrong text"), {"langgraph_node": "model"}))
        return
        yield

    base_ctx.agent.astream = _astream_redirect_scenario
    await executor.execute()

    messages_after = base_ctx.agent_input["messages"]
    ai_msgs = [m for m in messages_after if isinstance(m, AIMessage)]
    assert len(ai_msgs) >= 1
    partial_ai = ai_msgs[-1] if ai_msgs else None
    assert partial_ai is not None
    assert "Hello, " in partial_ai.content or "I think" in partial_ai.content

    human_msgs = [m for m in messages_after if isinstance(m, HumanMessage)]
    assert any("Wrong direction" in m.content for m in human_msgs)


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_execute_redirect_without_partial_text(fire_hook_mock, base_ctx):
    """Redirect with no partial text (immediate redirect before any streaming) still works."""
    from myrm_agent_harness.utils.runtime.steering import SteeringToken

    steering_token = SteeringToken()
    base_ctx.steering_token = steering_token

    executor = _make_executor(base_ctx)
    call_count = [0]

    async def _astream_immediate_redirect(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            steering_token.redirect("Changed my mind")
            yield ("messages", (AIMessage(content="ignored"), {"langgraph_node": "model"}))
        return
        yield

    base_ctx.agent.astream = _astream_immediate_redirect
    await executor.execute()

    assert call_count[0] == 2


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_execute_redirect_dedup_when_complete_aimessage_exists(fire_hook_mock, base_ctx):
    """Redirect after tool_calls: no duplicate AIMessage when updates already emitted one."""
    from langchain_core.messages import ToolMessage

    from myrm_agent_harness.utils.runtime.steering import SteeringToken

    steering_token = SteeringToken()
    base_ctx.steering_token = steering_token

    executor = _make_executor(base_ctx)
    call_count = [0]

    async def _astream_tool_then_redirect(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            yield ("messages", (AIMessage(content="I will search "), {"langgraph_node": "model"}))
            yield ("messages", (AIMessage(content="weather"), {"langgraph_node": "model"}))
            yield (
                "updates",
                {
                    "model": {
                        "messages": [
                            AIMessage(
                                content="I will search weather",
                                tool_calls=[{"id": "tc1", "name": "search", "args": {"q": "weather"}}],
                            )
                        ]
                    }
                },
            )
            yield ("updates", {"tools": {"messages": [ToolMessage(content="sunny", tool_call_id="tc1")]}})
            steering_token.redirect("No, search Shanghai")
            yield ("messages", (AIMessage(content="extra"), {"langgraph_node": "model"}))
        else:
            yield ("updates", {"model": {"messages": [AIMessage(content="Shanghai is sunny")]}})

    base_ctx.agent.astream = _astream_tool_then_redirect
    await executor.execute()

    messages_after = base_ctx.agent_input["messages"]
    ai_msgs = [m for m in messages_after if isinstance(m, AIMessage)]
    contents = [str(m.content) for m in ai_msgs]
    duplicates = [c for c in contents if contents.count(c) > 1]
    assert not duplicates, f"Duplicate AIMessage content found: {set(duplicates)}"


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_execute_subagent_notification(fire_hook_mock, base_ctx):
    """Subagent notification is emitted as SSE event without triggering new iteration."""
    drain_called = [False]

    def drain_fn():
        if not drain_called[0]:
            drain_called[0] = True
            return "Subagent completed: result summary"
        return None

    base_ctx.drain_subagent_notifications = drain_fn

    executor = _make_executor(base_ctx)
    base_ctx.agent.astream = _mock_astream_empty
    await executor.execute()

    events = executor._compactor.events
    subagent_events = [
        e for e in events if isinstance(e, dict) and e.get("type") == AgentEventType.SUBAGENT_COMPLETION.value
    ]
    assert len(subagent_events) == 1
    assert "Subagent completed" in str(subagent_events[0].get("data", ""))


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_emit_fatal_error_includes_recovery_actions_for_api_key(fire_hook_mock, base_ctx):
    """API key errors include recovery_actions in error event."""
    from myrm_agent_harness.toolkits.llms.errors import MyrmLLMError

    executor = _make_executor(base_ctx)

    async def _astream_api_key_error(*args, **kwargs):
        raise RuntimeError("Invalid API key: authentication failed (401)")
        yield

    base_ctx.agent.astream = _astream_api_key_error

    with pytest.raises(MyrmLLMError):
        await executor.execute()

    error_events = [
        e for e in executor._compactor.events if isinstance(e, dict) and e.get("type") == AgentEventType.ERROR.value
    ]
    assert len(error_events) == 1
    assert "diagnostic_result" in error_events[0]
    assert error_events[0]["diagnostic_result"]["error_type"] == "api_key"
    assert "recovery_actions" in error_events[0]
    actions = error_events[0]["recovery_actions"]
    assert len(actions) == 1
    assert actions[0]["id"] == "update_key"
    assert actions[0]["url"] == "/settings"


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_emit_fatal_error_includes_recovery_actions_for_billing(fire_hook_mock, base_ctx):
    """Billing errors include recovery_actions with top_up action."""
    from myrm_agent_harness.toolkits.llms.errors import MyrmLLMError

    executor = _make_executor(base_ctx)

    async def _astream_billing_error(*args, **kwargs):
        raise RuntimeError("You exceeded your current quota (402)")
        yield

    base_ctx.agent.astream = _astream_billing_error

    with pytest.raises(MyrmLLMError):
        await executor.execute()

    error_events = [
        e for e in executor._compactor.events if isinstance(e, dict) and e.get("type") == AgentEventType.ERROR.value
    ]
    assert len(error_events) == 1
    assert error_events[0]["diagnostic_result"]["error_type"] == "billing"
    assert "recovery_actions" in error_events[0]
    assert error_events[0]["recovery_actions"][0]["id"] == "top_up"


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_emit_fatal_error_includes_recovery_actions_for_model(fire_hook_mock, base_ctx):
    """Model-not-found errors include recovery_actions with change_model action."""
    from myrm_agent_harness.toolkits.llms.errors import MyrmLLMError

    executor = _make_executor(base_ctx)

    async def _astream_model_error(*args, **kwargs):
        raise RuntimeError("model not found: gpt-5-turbo does not exist")
        yield

    base_ctx.agent.astream = _astream_model_error

    with pytest.raises(MyrmLLMError):
        await executor.execute()

    error_events = [
        e for e in executor._compactor.events if isinstance(e, dict) and e.get("type") == AgentEventType.ERROR.value
    ]
    assert len(error_events) == 1
    assert error_events[0]["diagnostic_result"]["error_type"] == "model"
    assert "recovery_actions" in error_events[0]
    assert error_events[0]["recovery_actions"][0]["id"] == "change_model"
    assert error_events[0]["recovery_actions"][0]["url"] == "/settings"


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_emit_fatal_error_no_recovery_actions_for_unknown(fire_hook_mock, base_ctx):
    """Unknown errors do NOT include recovery_actions."""
    from myrm_agent_harness.toolkits.llms.errors import MyrmLLMError

    executor = _make_executor(base_ctx)

    async def _astream_unknown(*args, **kwargs):
        raise RuntimeError("unrecoverable internal error xyz")
        yield

    base_ctx.agent.astream = _astream_unknown

    with pytest.raises(MyrmLLMError):
        await executor.execute()

    error_events = [
        e for e in executor._compactor.events if isinstance(e, dict) and e.get("type") == AgentEventType.ERROR.value
    ]
    assert len(error_events) == 1
    assert "diagnostic_result" in error_events[0]
    assert error_events[0]["diagnostic_result"]["error_type"] == "unknown"
    assert "recovery_actions" not in error_events[0]


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
@patch("myrm_agent_harness.agent.errors.diagnostics.LLMErrorDiagnostic")
async def test_emit_fatal_error_no_recovery_actions_on_diagnostic_failure(diag_mock, fire_hook_mock, base_ctx):
    """When diagnostics crash, no recovery_actions field is emitted."""
    from myrm_agent_harness.toolkits.llms.errors import MyrmLLMError

    diag_mock.diagnose.side_effect = Exception("diagnostic engine crash")
    diag_mock.get_recovery_actions.side_effect = Exception("should not be called")
    executor = _make_executor(base_ctx)

    async def _astream_fatal(*args, **kwargs):
        raise RuntimeError("api key invalid (401)")
        yield

    base_ctx.agent.astream = _astream_fatal

    with pytest.raises(MyrmLLMError):
        await executor.execute()

    error_events = [
        e for e in executor._compactor.events if isinstance(e, dict) and e.get("type") == AgentEventType.ERROR.value
    ]
    assert len(error_events) == 1
    assert "diagnostic_result" not in error_events[0]
    assert "recovery_actions" not in error_events[0]


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_execute_with_token_tracker(fire_hook_mock, base_ctx):
    """Token tracker ContextVar is set when ctx.token_tracker is provided."""
    from myrm_agent_harness.utils.token_economics.tracker import (
        TokenTracker,
        _current_tracker,
    )

    tracker = TokenTracker()
    base_ctx.token_tracker = tracker

    executor = _make_executor(base_ctx)
    base_ctx.agent.astream = _mock_astream_normal

    captured_tracker = [None]

    async def _dispatch_capturing(*args, **kwargs):
        captured_tracker[0] = _current_tracker.get(None)

    with patch.object(executor, "_dispatch_chunk", side_effect=_dispatch_capturing):
        await executor.execute()

    assert captured_tracker[0] is tracker


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_execute_with_command_input(fire_hook_mock, base_ctx):
    """Command input mode (resume) skips messages list extraction."""
    from langgraph.types import Command

    base_ctx.agent_input = Command(resume="checkpoint_123")
    executor = _make_executor(base_ctx)
    base_ctx.agent.astream = _mock_astream_normal

    with patch.object(executor, "_dispatch_chunk", new_callable=AsyncMock):
        await executor.execute()

    assert executor._compactor.events[-1] is STREAM_DONE


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_execute_iteration_limit_in_goal_mode(fire_hook_mock, base_ctx):
    """Iteration limit with goal_provider falls through to goal continuation."""
    from langgraph.errors import GraphRecursionError

    base_ctx.goal_provider = MagicMock()
    base_ctx.goal_provider.current_goal = MagicMock()

    executor = _make_executor(base_ctx)
    call_count = [0]

    async def _astream_recursion_then_ok(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise GraphRecursionError("Recursion limit of 25 reached")
        yield ("messages", (AIMessage(content="done"), {"tags": []}))

    base_ctx.agent.astream = _astream_recursion_then_ok

    with (
        patch.object(executor, "_dispatch_chunk", new_callable=AsyncMock),
        patch.object(executor, "_handle_goal_continuation", new_callable=AsyncMock, return_value=False),
    ):
        await executor.execute()

    assert call_count[0] >= 1


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_execute_teammate_messages_triggers_continue(fire_hook_mock, base_ctx):
    """_handle_teammate_messages returning True triggers loop continuation."""
    executor = _make_executor(base_ctx)
    call_count = [0]

    async def _astream_two_turns(*args, **kwargs):
        call_count[0] += 1
        yield ("messages", (AIMessage(content=f"turn {call_count[0]}"), {"tags": []}))

    base_ctx.agent.astream = _astream_two_turns
    teammate_call = [0]

    original_handle_teammate = executor._handle_teammate_messages

    async def _mock_teammate(collected):
        teammate_call[0] += 1
        if teammate_call[0] == 1:
            return True
        return await original_handle_teammate(collected)

    with (
        patch.object(executor, "_dispatch_chunk", new_callable=AsyncMock),
        patch.object(executor, "_handle_teammate_messages", side_effect=_mock_teammate),
    ):
        await executor.execute()

    assert call_count[0] == 2


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_execute_escalation_triggers_continue(fire_hook_mock, base_ctx):
    """_handle_escalation returning True triggers loop continuation."""
    executor = _make_executor(base_ctx)
    call_count = [0]

    async def _astream_multi(*args, **kwargs):
        call_count[0] += 1
        yield ("messages", (AIMessage(content=f"turn {call_count[0]}"), {"tags": []}))

    base_ctx.agent.astream = _astream_multi
    escalation_call = [0]

    async def _mock_escalation(collected):
        escalation_call[0] += 1
        return escalation_call[0] == 1

    with (
        patch.object(executor, "_dispatch_chunk", new_callable=AsyncMock),
        patch.object(executor, "_handle_escalation", side_effect=_mock_escalation),
    ):
        await executor.execute()

    assert call_count[0] == 2


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_execute_length_truncation_triggers_continue(fire_hook_mock, base_ctx):
    """_handle_length_truncation returning True increments counter and continues."""
    executor = _make_executor(base_ctx)
    call_count = [0]

    async def _astream_multi(*args, **kwargs):
        call_count[0] += 1
        yield ("messages", (AIMessage(content=f"turn {call_count[0]}"), {"tags": []}))

    base_ctx.agent.astream = _astream_multi
    trunc_call = [0]

    async def _mock_truncation(collected, retries):
        trunc_call[0] += 1
        return trunc_call[0] == 1

    with (
        patch.object(executor, "_dispatch_chunk", new_callable=AsyncMock),
        patch.object(executor, "_handle_length_truncation", side_effect=_mock_truncation),
    ):
        await executor.execute()

    assert call_count[0] == 2


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_execute_safety_refusal_triggers_continue(fire_hook_mock, base_ctx):
    """_handle_safety_refusal_fallback returning True triggers loop continuation."""
    executor = _make_executor(base_ctx)
    call_count = [0]

    async def _astream_multi(*args, **kwargs):
        call_count[0] += 1
        yield ("messages", (AIMessage(content=f"turn {call_count[0]}"), {"tags": []}))

    base_ctx.agent.astream = _astream_multi
    refusal_call = [0]

    async def _mock_refusal():
        refusal_call[0] += 1
        return refusal_call[0] == 1

    with (
        patch.object(executor, "_dispatch_chunk", new_callable=AsyncMock),
        patch.object(executor, "_handle_safety_refusal_fallback", side_effect=_mock_refusal),
    ):
        await executor.execute()

    assert call_count[0] == 2


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_execute_empty_response_triggers_continue(fire_hook_mock, base_ctx):
    """_handle_empty_response returning True increments counter and continues."""
    executor = _make_executor(base_ctx)
    call_count = [0]

    async def _astream_multi(*args, **kwargs):
        call_count[0] += 1
        yield ("messages", (AIMessage(content=f"turn {call_count[0]}"), {"tags": []}))

    base_ctx.agent.astream = _astream_multi
    empty_call = [0]

    async def _mock_empty(collected, retries):
        empty_call[0] += 1
        return empty_call[0] == 1

    with (
        patch.object(executor, "_dispatch_chunk", new_callable=AsyncMock),
        patch.object(executor, "_handle_empty_response", side_effect=_mock_empty),
    ):
        await executor.execute()

    assert call_count[0] == 2


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_execute_escalation_scrubber_flush(fire_hook_mock, base_ctx):
    """Escalation scrubber pending content is flushed in finally block."""
    executor = _make_executor(base_ctx)
    base_ctx.agent.astream = _mock_astream_normal

    executor._escalation_scrubber.flush = MagicMock(return_value="escalated text")
    executor._reasoning_scrubber.process = MagicMock(return_value=[(AgentEventType.MESSAGE, "clean text")])

    with (
        patch.object(executor, "_dispatch_chunk", new_callable=AsyncMock),
        patch.object(executor, "_emit_event", new_callable=AsyncMock) as emit_mock,
    ):
        await executor.execute()

    emitted_dicts = [call.args[0] for call in emit_mock.call_args_list]
    assert any(d.get("type") == AgentEventType.MESSAGE.value and d.get("data") == "clean text" for d in emitted_dicts)
