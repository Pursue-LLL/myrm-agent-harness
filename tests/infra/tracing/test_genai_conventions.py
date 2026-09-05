"""Unit tests for OpenTelemetry GenAI Semantic Conventions and Trace Performance calculation."""

from myrm_agent_harness.infra.tracing.tracer import (
    GEN_AI_SYSTEM,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
    GEN_AI_USAGE_CACHE_READ_TOKENS,
    GEN_AI_TOOL_NAME,
    GEN_AI_TOOL_CALL_ID,
    GEN_AI_TOOL_STATUS,
    GEN_AI_AGENT_TURN,
    GEN_AI_SERVER_TTFT_MS,
)
from myrm_agent_harness.agent.event_log.trace_types import LLMCallRecord, ToolCallRecord, ExecutionTrace


def test_genai_constants_defined():
    """Verify standard GenAI attribute keys conform to OpenTelemetry specs."""
    assert GEN_AI_SYSTEM == "gen_ai.system"
    assert GEN_AI_REQUEST_MODEL == "gen_ai.request.model"
    assert GEN_AI_USAGE_INPUT_TOKENS == "gen_ai.usage.input_tokens"
    assert GEN_AI_USAGE_OUTPUT_TOKENS == "gen_ai.usage.output_tokens"
    assert GEN_AI_USAGE_CACHE_READ_TOKENS == "gen_ai.usage.cache_read_tokens"
    assert GEN_AI_TOOL_NAME == "gen_ai.tool.name"
    assert GEN_AI_TOOL_CALL_ID == "gen_ai.tool.call.id"
    assert GEN_AI_TOOL_STATUS == "gen_ai.tool.status"
    assert GEN_AI_AGENT_TURN == "gen_ai.agent.turn"
    assert GEN_AI_SERVER_TTFT_MS == "gen_ai.server.ttft_ms"


def test_llm_call_record_cache_read_tokens():
    """Verify LLMCallRecord retains and exports cache_read_tokens."""
    record = LLMCallRecord(
        sequence=1,
        start_time=100.0,
        end_time=102.5,
        model_name="deepseek-chat",
        duration_ms=2500.0,
        ttft_ms=650.0,
        prompt_tokens=1500,
        completion_tokens=300,
        total_tokens=1800,
        cache_read_tokens=1200,
    )
    assert record.cache_read_tokens == 1200

    trace = ExecutionTrace(
        session_id="test-session-123",
        llm_calls=[record],
        tool_calls=[
            ToolCallRecord(
                sequence=2,
                tool_name="web_search",
                start_time=103.0,
                end_time=105.0,
                duration_ms=2000.0,
                success=True,
            )
        ],
    )

    data = trace.to_dict()
    assert len(data["llm_calls"]) == 1
    assert data["llm_calls"][0]["cache_read_tokens"] == 1200
    assert data["llm_calls"][0]["model_name"] == "deepseek-chat"


def test_record_gen_ai_helpers():
    """Verify record_gen_ai_* helper functions populate span attributes accurately."""
    from unittest.mock import MagicMock
    from myrm_agent_harness.infra.tracing.gen_ai_conventions import (
        record_gen_ai_agent_turn,
        record_gen_ai_llm_request,
        record_gen_ai_tool_call,
        SPAN_AGENT_TURN,
        SPAN_LLM_REQUEST,
        SPAN_TOOL_CALL,
        GEN_AI_SYSTEM,
        GEN_AI_OPERATION_NAME,
        GEN_AI_CONVERSATION_ID,
        GEN_AI_REQUEST_MODEL,
        GEN_AI_USAGE_INPUT_TOKENS,
        GEN_AI_USAGE_OUTPUT_TOKENS,
        GEN_AI_USAGE_TOTAL_TOKENS,
        GEN_AI_USAGE_CACHE_READ_TOKENS,
        GEN_AI_CACHE_HIT_RATIO,
        GEN_AI_LATENCY_TTFT_MS,
        GEN_AI_TOOL_NAME,
        GEN_AI_TOOL_STATUS,
    )

    # 1. Agent Turn Span
    mock_turn_span = MagicMock()
    mock_turn_span.is_recording.return_value = True
    record_gen_ai_agent_turn(
        mock_turn_span,
        conversation_id="conv-123",
        turn_id="turn-1",
        agent_type="code_analyst",
        query_preview="Check performance bugs",
        status="success",
    )
    mock_turn_span.set_attribute.assert_any_call(GEN_AI_SYSTEM, "myrm")
    mock_turn_span.set_attribute.assert_any_call(GEN_AI_OPERATION_NAME, "agent.turn")
    mock_turn_span.set_attribute.assert_any_call(GEN_AI_CONVERSATION_ID, "conv-123")
    mock_turn_span.set_attribute.assert_any_call("agent.type", "code_analyst")
    mock_turn_span.set_attribute.assert_any_call("gen_ai.input.summary", "Check performance bugs")
    mock_turn_span.set_attribute.assert_any_call("gen_ai.status", "success")

    # 2. LLM Request Span with cache accounting
    mock_llm_span = MagicMock()
    mock_llm_span.is_recording.return_value = True
    record_gen_ai_llm_request(
        mock_llm_span,
        model_name="deepseek-v3",
        prompt_tokens=10000,
        completion_tokens=500,
        cache_read_tokens=8500,
        reasoning_tokens=200,
        ttft_ms=320.5,
        attempt=1,
    )
    mock_llm_span.set_attribute.assert_any_call(GEN_AI_SYSTEM, "myrm")
    mock_llm_span.set_attribute.assert_any_call(GEN_AI_OPERATION_NAME, "llm.request")
    mock_llm_span.set_attribute.assert_any_call(GEN_AI_REQUEST_MODEL, "deepseek-v3")
    mock_llm_span.set_attribute.assert_any_call(GEN_AI_USAGE_INPUT_TOKENS, 10000)
    mock_llm_span.set_attribute.assert_any_call(GEN_AI_USAGE_OUTPUT_TOKENS, 500)
    mock_llm_span.set_attribute.assert_any_call(GEN_AI_USAGE_TOTAL_TOKENS, 10500)
    mock_llm_span.set_attribute.assert_any_call(GEN_AI_USAGE_CACHE_READ_TOKENS, 8500)
    mock_llm_span.set_attribute.assert_any_call(GEN_AI_CACHE_HIT_RATIO, 0.85)
    mock_llm_span.set_attribute.assert_any_call(GEN_AI_LATENCY_TTFT_MS, 320.5)

    # 3. Tool Call Span
    mock_tool_span = MagicMock()
    mock_tool_span.is_recording.return_value = True
    record_gen_ai_tool_call(
        mock_tool_span,
        tool_name="bash",
        tool_call_id="call-456",
        status="success",
        duration_ms=125.0,
    )
    mock_tool_span.set_attribute.assert_any_call(GEN_AI_SYSTEM, "myrm")
    mock_tool_span.set_attribute.assert_any_call(GEN_AI_OPERATION_NAME, "tool.call")
    mock_tool_span.set_attribute.assert_any_call(GEN_AI_TOOL_NAME, "bash")
    mock_tool_span.set_attribute.assert_any_call(GEN_AI_TOOL_STATUS, "success")
    mock_tool_span.set_attribute.assert_any_call("gen_ai.tool.duration_ms", 125.0)

