"""Trace context propagation for distributed tracing.

Provides inject/extract utilities for propagating trace context across service boundaries.

[INPUT]
- opentelemetry.propagate (POS: Context propagation API)

[OUTPUT]
- inject_trace_context: 注入trace context
- extract_trace_context: 提取trace context

[POS]
Trace context propagation. Maintains complete trace chains across service calls.

"""

from __future__ import annotations

from typing import Any

from opentelemetry import propagate, trace
from opentelemetry.context import Context


def inject_trace_context(carrier: dict[str, Any] | None = None) -> dict[str, Any]:
    """Inject current trace context into carrier.

    Used when making outbound requests to propagate trace context.

    Args:
        carrier: Optional carrier dict to inject into (creates new if None)

    Returns:
        Carrier dict with injected trace context

    Example:
        headers = inject_trace_context()
        response = await http_client.post(url, headers=headers, ...)
    """
    if carrier is None:
        carrier = {}

    propagate.inject(carrier)
    return carrier


def extract_trace_context(carrier: dict[str, Any]) -> Context:
    """Extract trace context from carrier.

    Used when receiving inbound requests to continue trace from parent.

    Args:
        carrier: Carrier dict containing trace context (e.g., HTTP headers)

    Returns:
        OpenTelemetry context with extracted trace

    Example:
        context = extract_trace_context(request.headers)
        with tracer.start_as_current_span("handle_request", context=context):
            ...
    """
    return propagate.extract(carrier)


def get_current_trace_id() -> str | None:
    """Get current trace ID as hex string.

    Returns:
        Trace ID or None if no active span
    """
    span = trace.get_current_span()
    if span and span.get_span_context().is_valid:
        trace_id = span.get_span_context().trace_id
        return format(trace_id, "032x")
    return None


def get_current_span_id() -> str | None:
    """Get current span ID as hex string.

    Returns:
        Span ID or None if no active span
    """
    span = trace.get_current_span()
    if span and span.get_span_context().is_valid:
        span_id = span.get_span_context().span_id
        return format(span_id, "016x")
    return None
