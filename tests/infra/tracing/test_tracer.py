"""Unit tests for OpenTelemetry tracer."""

import pytest

from myrm_agent_harness.infra.tracing import (
    get_tracer,
    setup_tracing,
    trace_async,
    trace_context,
)


def test_get_tracer_returns_noop_without_setup():
    """get_tracer returns a NoOp tracer when setup_tracing has not been called."""
    tracer = get_tracer("noop_module")
    assert tracer is not None


def test_setup_tracing():
    """Test tracing initialization."""
    setup_tracing(service_name="test-service", console_export=False)

    tracer = get_tracer("test_module")
    assert tracer is not None


def test_trace_context():
    """Test trace context manager."""
    setup_tracing(service_name="test-service", console_export=False)

    with trace_context("test_module", "test_operation", {"key": "value"}) as span:
        assert span is not None
        span.set_attribute("custom", "attribute")


def test_trace_context_with_error():
    """Test trace context with exception."""
    setup_tracing(service_name="test-service", console_export=False)

    with pytest.raises(ValueError), trace_context("test_module", "test_operation"):
        raise ValueError("Test error")


@pytest.mark.asyncio
async def test_trace_async_decorator():
    """Test async function tracing decorator."""
    setup_tracing(service_name="test-service", console_export=False)

    @trace_async()
    async def test_function(arg: str) -> str:
        return arg.upper()

    result = await test_function("hello")
    assert result == "HELLO"


@pytest.mark.asyncio
async def test_trace_async_with_error():
    """Test async decorator with exception."""
    setup_tracing(service_name="test-service", console_export=False)

    @trace_async()
    async def failing_function() -> None:
        raise ValueError("Test error")

    with pytest.raises(ValueError):
        await failing_function()


@pytest.mark.asyncio
async def test_trace_async_with_kwargs():
    """Test async decorator with kwargs."""
    setup_tracing(service_name="test-service", console_export=False)

    @trace_async()
    async def function_with_kwargs(channel: str, recipient: str) -> str:
        return f"{channel}:{recipient}"

    result = await function_with_kwargs(channel="telegram", recipient="user123")
    assert result == "telegram:user123"


def test_record_gen_ai_semantic_conventions():
    """Test GenAI Semantic Conventions helper functions with recording mock span."""
    from unittest.mock import MagicMock
    from opentelemetry.trace import Span
    from myrm_agent_harness.infra.tracing import (
        GEN_AI_CACHE_HIT_RATIO,
        GEN_AI_OPERATION_NAME,
        GEN_AI_REQUEST_MODEL,
        GEN_AI_SYSTEM,
        GEN_AI_TOOL_NAME,
        GEN_AI_USAGE_CACHE_READ_TOKENS,
        GEN_AI_USAGE_INPUT_TOKENS,
        SPAN_AGENT_TURN,
        record_gen_ai_agent_turn,
        record_gen_ai_llm_request,
        record_gen_ai_tool_call,
    )

    # 1. Agent Turn Span
    mock_turn_span = MagicMock(spec=Span)
    mock_turn_span.is_recording.return_value = True
    record_gen_ai_agent_turn(
        mock_turn_span,
        conversation_id="conv-123",
        turn_id="turn-1",
        agent_type="SkillAgent",
        query_preview="Check weather in Tokyo",
        status="completed",
    )
    mock_turn_span.set_attribute.assert_any_call(GEN_AI_SYSTEM, "myrm")
    mock_turn_span.set_attribute.assert_any_call(GEN_AI_OPERATION_NAME, "agent.turn")
    mock_turn_span.set_attribute.assert_any_call("agent.type", "SkillAgent")

    # 2. LLM Request Span with Token & Cache Hit Accounting
    mock_llm_span = MagicMock(spec=Span)
    mock_llm_span.is_recording.return_value = True
    record_gen_ai_llm_request(
        mock_llm_span,
        model_name="deepseek-chat",
        prompt_tokens=1000,
        completion_tokens=200,
        cache_read_tokens=800,
        reasoning_tokens=50,
        ttft_ms=120.5,
    )
    mock_llm_span.set_attribute.assert_any_call(GEN_AI_REQUEST_MODEL, "deepseek-chat")
    mock_llm_span.set_attribute.assert_any_call(GEN_AI_USAGE_INPUT_TOKENS, 1000)
    mock_llm_span.set_attribute.assert_any_call(GEN_AI_USAGE_CACHE_READ_TOKENS, 800)
    mock_llm_span.set_attribute.assert_any_call(GEN_AI_CACHE_HIT_RATIO, 0.8)

    # 3. Tool Call Span
    mock_tool_span = MagicMock(spec=Span)
    mock_tool_span.is_recording.return_value = True
    record_gen_ai_tool_call(
        mock_tool_span,
        tool_name="web_search",
        tool_call_id="call-456",
        status="success",
        duration_ms=350.0,
    )
    mock_tool_span.set_attribute.assert_any_call(GEN_AI_TOOL_NAME, "web_search")
    mock_tool_span.set_attribute.assert_any_call("gen_ai.tool.call_id", "call-456")

    # 4. Non-recording span safety (no-op)
    non_recording = MagicMock(spec=Span)
    non_recording.is_recording.return_value = False
    record_gen_ai_agent_turn(non_recording)
    non_recording.set_attribute.assert_not_called()

