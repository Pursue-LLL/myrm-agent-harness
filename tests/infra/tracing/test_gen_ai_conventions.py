"""Unit tests for OpenTelemetry GenAI Semantic Conventions and Span Helpers."""

from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.infra.tracing.gen_ai_conventions import (
    GEN_AI_CACHE_HIT_RATIO,
    GEN_AI_CONVERSATION_ID,
    GEN_AI_LATENCY_TTFT_MS,
    GEN_AI_OPERATION_NAME,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_RESPONSE_MODEL,
    GEN_AI_SYSTEM,
    GEN_AI_TOOL_CALL_ID,
    GEN_AI_TOOL_DURATION_MS,
    GEN_AI_TOOL_NAME,
    GEN_AI_TOOL_STATUS,
    GEN_AI_TURN_ID,
    GEN_AI_USAGE_CACHE_READ_TOKENS,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
    GEN_AI_USAGE_REASONING_TOKENS,
    GEN_AI_USAGE_TOTAL_TOKENS,
    SPAN_AGENT_TURN,
    SPAN_LLM_REQUEST,
    SPAN_TOOL_CALL,
    record_gen_ai_agent_turn,
    record_gen_ai_llm_request,
    record_gen_ai_tool_call,
)


def _create_mock_span(is_recording: bool = True) -> MagicMock:
    span = MagicMock()
    span.is_recording.return_value = is_recording
    span._attrs = {}

    def set_attr(key: str, val: object) -> None:
        span._attrs[key] = val

    span.set_attribute.side_effect = set_attr
    return span


def test_span_constants():
    """Verify standard three-tier span names."""
    assert SPAN_AGENT_TURN == "agent.turn"
    assert SPAN_LLM_REQUEST == "llm.request"
    assert SPAN_TOOL_CALL == "tool.call"


def test_record_agent_turn_span():
    """Verify standard agent.turn root span attributes."""
    span = _create_mock_span()
    record_gen_ai_agent_turn(
        span,
        conversation_id="conv-123",
        turn_id="turn-456",
        agent_type="ReactAgent",
        query_preview="What is the weather today?",
        status="completed",
    )

    assert span._attrs[GEN_AI_SYSTEM] == "myrm"
    assert span._attrs[GEN_AI_OPERATION_NAME] == "agent.turn"
    assert span._attrs[GEN_AI_CONVERSATION_ID] == "conv-123"
    assert span._attrs[GEN_AI_TURN_ID] == "turn-456"
    assert span._attrs["agent.type"] == "ReactAgent"
    assert span._attrs["gen_ai.input.summary"] == "What is the weather today?"
    assert span._attrs["gen_ai.status"] == "completed"


def test_record_agent_turn_non_recording_span():
    """Non-recording span should not set attributes."""
    span = _create_mock_span(is_recording=False)
    record_gen_ai_agent_turn(span, conversation_id="conv-123")
    assert len(span._attrs) == 0


def test_record_llm_request_with_cache_hit():
    """Verify standard llm.request token accounting and cache hit ratio calculation."""
    span = _create_mock_span()
    record_gen_ai_llm_request(
        span,
        model_name="deepseek-v3",
        prompt_tokens=10000,
        completion_tokens=500,
        cache_read_tokens=8500,
        reasoning_tokens=200,
        ttft_ms=350.5,
        attempt=1,
    )

    assert span._attrs[GEN_AI_SYSTEM] == "myrm"
    assert span._attrs[GEN_AI_OPERATION_NAME] == "llm.request"
    assert span._attrs[GEN_AI_REQUEST_MODEL] == "deepseek-v3"
    assert span._attrs[GEN_AI_RESPONSE_MODEL] == "deepseek-v3"
    assert span._attrs[GEN_AI_USAGE_INPUT_TOKENS] == 10000
    assert span._attrs[GEN_AI_USAGE_OUTPUT_TOKENS] == 500
    assert span._attrs[GEN_AI_USAGE_TOTAL_TOKENS] == 10500
    assert span._attrs[GEN_AI_USAGE_CACHE_READ_TOKENS] == 8500
    assert span._attrs[GEN_AI_USAGE_REASONING_TOKENS] == 200
    assert span._attrs[GEN_AI_CACHE_HIT_RATIO] == 0.85
    assert span._attrs[GEN_AI_LATENCY_TTFT_MS] == 350.5


def test_record_llm_request_zero_tokens_safety():
    """Verify division-by-zero protection when input tokens is zero."""
    span = _create_mock_span()
    record_gen_ai_llm_request(
        span,
        model_name="gpt-4o",
        prompt_tokens=0,
        completion_tokens=0,
        cache_read_tokens=0,
    )

    assert span._attrs[GEN_AI_USAGE_INPUT_TOKENS] == 0
    assert GEN_AI_CACHE_HIT_RATIO not in span._attrs


def test_record_tool_call_span():
    """Verify standard tool.call span attributes."""
    span = _create_mock_span()
    record_gen_ai_tool_call(
        span,
        tool_name="web_search",
        tool_call_id="call_999",
        status="success",
        duration_ms=450.2,
    )

    assert span._attrs[GEN_AI_SYSTEM] == "myrm"
    assert span._attrs[GEN_AI_OPERATION_NAME] == "tool.call"
    assert span._attrs[GEN_AI_TOOL_NAME] == "web_search"
    assert span._attrs[GEN_AI_TOOL_CALL_ID] == "call_999"
    assert span._attrs[GEN_AI_TOOL_STATUS] == "success"
    assert span._attrs[GEN_AI_TOOL_DURATION_MS] == 450.2
