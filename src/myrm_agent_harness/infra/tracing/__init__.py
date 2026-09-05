"""Distributed tracing and metrics with OpenTelemetry.

Provides call chain tracing and metrics collection for observability.

Design: The framework provides consumer APIs (get_tracer, get_meter, trace_async,
trace_context) that work with OpenTelemetry's default NoOp provider when no
TracerProvider/MeterProvider is configured — zero overhead by default.

Initialization functions (setup_tracing, setup_metrics) are convenience helpers
intended for the business layer. The framework never calls them automatically.

[INPUT]
- opentelemetry-api (POS: 追踪API)
- opentelemetry-sdk (POS: 追踪SDK)

[OUTPUT]
- setup_tracing: 初始化追踪（业务层调用）
- setup_metrics: 初始化 Metrics 导出（业务层调用）
- get_tracer: 获取追踪器（框架内部使用）
- get_meter: 获取 Meter 实例（框架内部使用）
- trace_async: 异步函数追踪装饰器（框架内部使用）
- MetricsExporter: 导出器类型

[POS]
Distributed tracing and metrics collection. Integrates OpenTelemetry for call chain tracing, performance analysis, and metrics export.

"""

from .gen_ai_conventions import (
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
from .metrics import (
    DynamicLabelManager,
    MetricsExporter,
    get_meter,
    setup_metrics,
    shutdown_metrics,
)
from .propagation import (
    extract_trace_context,
    get_current_span_id,
    get_current_trace_id,
    inject_trace_context,
)
from .sampling import IntelligentSampler, create_intelligent_sampler
from .tracer import (
    get_tracer,
    setup_tracing,
    shutdown_tracing,
    trace_async,
    trace_context,
)

__all__ = [
    "DynamicLabelManager",
    "GEN_AI_CACHE_HIT_RATIO",
    "GEN_AI_CONVERSATION_ID",
    "GEN_AI_LATENCY_TTFT_MS",
    "GEN_AI_OPERATION_NAME",
    "GEN_AI_REQUEST_MODEL",
    "GEN_AI_RESPONSE_MODEL",
    "GEN_AI_SYSTEM",
    "GEN_AI_TOOL_CALL_ID",
    "GEN_AI_TOOL_DURATION_MS",
    "GEN_AI_TOOL_NAME",
    "GEN_AI_TOOL_STATUS",
    "GEN_AI_TURN_ID",
    "GEN_AI_USAGE_CACHE_READ_TOKENS",
    "GEN_AI_USAGE_INPUT_TOKENS",
    "GEN_AI_USAGE_OUTPUT_TOKENS",
    "GEN_AI_USAGE_REASONING_TOKENS",
    "GEN_AI_USAGE_TOTAL_TOKENS",
    "IntelligentSampler",
    "MetricsExporter",
    "SPAN_AGENT_TURN",
    "SPAN_LLM_REQUEST",
    "SPAN_TOOL_CALL",
    "create_intelligent_sampler",
    "extract_trace_context",
    "get_current_span_id",
    "get_current_trace_id",
    "get_meter",
    "get_tracer",
    "inject_trace_context",
    "record_gen_ai_agent_turn",
    "record_gen_ai_llm_request",
    "record_gen_ai_tool_call",
    "setup_metrics",
    "setup_tracing",
    "shutdown_metrics",
    "shutdown_tracing",
    "trace_async",
    "trace_context",
]
