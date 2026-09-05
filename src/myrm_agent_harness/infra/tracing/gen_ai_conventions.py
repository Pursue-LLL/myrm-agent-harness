"""OpenTelemetry GenAI Semantic Conventions and Span Helpers.

[INPUT]
- opentelemetry.trace (POS: 分布式追踪核心API)

[OUTPUT]
- Standard GenAI semantic convention constants (SPAN_AGENT_TURN, SPAN_LLM_REQUEST, SPAN_TOOL_CALL, etc.)
- record_gen_ai_agent_turn: Helper to annotate agent turn root spans
- record_gen_ai_llm_request: Helper to annotate LLM request spans with token accounting & cache hits
- record_gen_ai_tool_call: Helper to annotate tool execution spans

[POS]
Defines official OpenTelemetry Generative AI Semantic Conventions for the three-tier
trace hierarchy (agent.turn -> llm.request -> tool.call) and prompt cache accounting.
"""

from __future__ import annotations

from opentelemetry.trace import Span

# --- Standard GenAI Span Names ---
SPAN_AGENT_TURN: str = "agent.turn"
SPAN_LLM_REQUEST: str = "llm.request"
SPAN_TOOL_CALL: str = "tool.call"

# --- GenAI Semantic Attributes (OTel GenAI v0.6+ SSOT) ---
GEN_AI_SYSTEM: str = "gen_ai.system"
GEN_AI_OPERATION_NAME: str = "gen_ai.operation.name"
GEN_AI_CONVERSATION_ID: str = "gen_ai.conversation.id"
GEN_AI_TURN_ID: str = "gen_ai.turn.id"

# Request / Response Model
GEN_AI_REQUEST_MODEL: str = "gen_ai.request.model"
GEN_AI_RESPONSE_MODEL: str = "gen_ai.response.model"

# Token Accounting & Prompt Cache
GEN_AI_USAGE_INPUT_TOKENS: str = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS: str = "gen_ai.usage.output_tokens"
GEN_AI_USAGE_CACHE_READ_TOKENS: str = "gen_ai.usage.cache_read_tokens"
GEN_AI_USAGE_REASONING_TOKENS: str = "gen_ai.usage.reasoning_tokens"
GEN_AI_USAGE_TOTAL_TOKENS: str = "gen_ai.usage.total_tokens"
GEN_AI_CACHE_HIT_RATIO: str = "gen_ai.usage.cache_hit_ratio"
GEN_AI_LATENCY_TTFT_MS: str = "gen_ai.latency.ttft_ms"

# Tool Execution
GEN_AI_TOOL_NAME: str = "gen_ai.tool.name"
GEN_AI_TOOL_CALL_ID: str = "gen_ai.tool.call_id"
GEN_AI_TOOL_STATUS: str = "gen_ai.tool.status"
GEN_AI_TOOL_DURATION_MS: str = "gen_ai.tool.duration_ms"


def record_gen_ai_agent_turn(
    span: Span,
    conversation_id: str | None = None,
    turn_id: str | None = None,
    agent_type: str | None = None,
    query_preview: str | None = None,
    status: str = "in_progress",
) -> None:
    """Annotate root agent.turn span with standard GenAI attributes."""
    if not span.is_recording():
        return
    span.set_attribute(GEN_AI_SYSTEM, "myrm")
    span.set_attribute(GEN_AI_OPERATION_NAME, "agent.turn")
    if conversation_id:
        span.set_attribute(GEN_AI_CONVERSATION_ID, conversation_id)
    if turn_id:
        span.set_attribute(GEN_AI_TURN_ID, turn_id)
    if agent_type:
        span.set_attribute("agent.type", agent_type)
    if query_preview:
        span.set_attribute("gen_ai.input.summary", query_preview[:300])
    span.set_attribute("gen_ai.status", status)


def record_gen_ai_llm_request(
    span: Span,
    model_name: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cache_read_tokens: int = 0,
    reasoning_tokens: int = 0,
    ttft_ms: float | None = None,
    attempt: int = 1,
) -> None:
    """Annotate llm.request span with standard GenAI token accounting and cache hit ratio."""
    if not span.is_recording():
        return
    span.set_attribute(GEN_AI_SYSTEM, "myrm")
    span.set_attribute(GEN_AI_OPERATION_NAME, "llm.request")
    span.set_attribute(GEN_AI_REQUEST_MODEL, model_name)
    span.set_attribute(GEN_AI_RESPONSE_MODEL, model_name)
    span.set_attribute("gen_ai.request.attempt", attempt)

    total_input = max(0, prompt_tokens)
    total_output = max(0, completion_tokens)
    cache_read = max(0, cache_read_tokens)
    reasoning = max(0, reasoning_tokens)

    span.set_attribute(GEN_AI_USAGE_INPUT_TOKENS, total_input)
    span.set_attribute(GEN_AI_USAGE_OUTPUT_TOKENS, total_output)
    span.set_attribute(GEN_AI_USAGE_TOTAL_TOKENS, total_input + total_output)
    span.set_attribute(GEN_AI_USAGE_CACHE_READ_TOKENS, cache_read)
    span.set_attribute(GEN_AI_USAGE_REASONING_TOKENS, reasoning)

    if total_input > 0:
        hit_ratio = round(cache_read / total_input, 4)
        span.set_attribute(GEN_AI_CACHE_HIT_RATIO, hit_ratio)

    if ttft_ms is not None and ttft_ms >= 0:
        span.set_attribute(GEN_AI_LATENCY_TTFT_MS, round(ttft_ms, 2))


def record_gen_ai_tool_call(
    span: Span,
    tool_name: str,
    tool_call_id: str | None = None,
    status: str = "success",
    duration_ms: float | None = None,
) -> None:
    """Annotate tool.call span with standard GenAI tool attributes."""
    if not span.is_recording():
        return
    span.set_attribute(GEN_AI_SYSTEM, "myrm")
    span.set_attribute(GEN_AI_OPERATION_NAME, "tool.call")
    span.set_attribute(GEN_AI_TOOL_NAME, tool_name)
    span.set_attribute(GEN_AI_TOOL_STATUS, status)
    if tool_call_id:
        span.set_attribute(GEN_AI_TOOL_CALL_ID, tool_call_id)
    if duration_ms is not None and duration_ms >= 0:
        span.set_attribute(GEN_AI_TOOL_DURATION_MS, round(duration_ms, 2))
