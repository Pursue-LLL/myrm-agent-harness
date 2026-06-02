"""Intelligent sampling strategy for OpenTelemetry tracing.

Implements multi-layer sampling rules to reduce overhead while preserving critical information.

[INPUT]
- opentelemetry.sdk.trace.sampling (POS: Sampling API)

[OUTPUT]
- IntelligentSampler: 智能采样器

[POS]
Intelligent sampling strategy. 100% for errors, 100% for slow requests, 100% for critical paths, 10% for normal requests.

"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from opentelemetry import trace

try:
    from opentelemetry.sdk.trace.sampling import (
        Decision,
        ParentBased,
        Sampler,
        SamplingResult,
        TraceIdRatioBased,
    )

    HAS_OTEL_SDK = True
except (ImportError, TypeError):
    HAS_OTEL_SDK = False
    Decision = Any  # type: ignore
    ParentBased = Any  # type: ignore
    Sampler = object  # type: ignore
    SamplingResult = Any  # type: ignore
    TraceIdRatioBased = Any  # type: ignore


from opentelemetry.trace import Link, SpanKind
from opentelemetry.util.types import Attributes


class IntelligentSampler(Sampler):
    """Intelligent sampler with multi-layer rules.

    Sampling rules (priority order):
    1. Error requests: 100% (for debugging)
    2. Slow requests: 100% (>1s duration, detected via attributes)
    3. Critical paths: 100% (model calls, message delivery)
    4. Normal requests: 10% (reduce overhead)

    Features:
    - Context-aware: Uses span attributes for decisions
    - Parent-based: Respects parent sampling decisions
    - Configurable: Adjustable thresholds and rates
    """

    def __init__(
        self,
        base_rate: float = 0.1,
        slow_threshold_ms: float = 1000.0,
        critical_span_prefixes: tuple[str, ...] = (
            "model_fallback",
            "delivery_",
            "llm_call",
        ),
    ) -> None:
        """Initialize intelligent sampler.

        Args:
            base_rate: Base sampling rate for normal requests (default: 0.1 = 10%)
            slow_threshold_ms: Threshold for slow requests in milliseconds (default: 1000ms)
            critical_span_prefixes: Span name prefixes for critical paths
        """
        self.base_rate = base_rate
        self.slow_threshold_ms = slow_threshold_ms
        self.critical_span_prefixes = critical_span_prefixes
        self._base_sampler = TraceIdRatioBased(base_rate)

    def should_sample(
        self,
        parent_context: trace.SpanContext | None,
        trace_id: int,
        name: str,
        kind: SpanKind | None = None,
        attributes: Attributes | None = None,
        links: Sequence[Link] | None = None,
        trace_state: trace.TraceState | None = None,
    ) -> SamplingResult:
        """Determine if span should be sampled.

        Args:
            parent_context: Parent span context
            trace_id: Trace ID
            name: Span name
            kind: Span kind
            attributes: Span attributes
            links: Span links
            trace_state: Trace state

        Returns:
            Sampling result
        """
        # Rule 1: Respect parent sampling decision
        if parent_context is not None and parent_context.is_valid and parent_context.trace_flags.sampled:
            return SamplingResult(
                Decision.RECORD_AND_SAMPLE,
                attributes=attributes,
                trace_state=trace_state,
            )

        # Rule 2: Error requests - 100% sampling
        if attributes:
            # Check for error indicators
            if "error" in attributes or "exception" in attributes:
                return SamplingResult(
                    Decision.RECORD_AND_SAMPLE,
                    attributes=attributes,
                    trace_state=trace_state,
                )

            # Check for failure status
            status = attributes.get("status")
            if status in ("failed", "error", "failure"):
                return SamplingResult(
                    Decision.RECORD_AND_SAMPLE,
                    attributes=attributes,
                    trace_state=trace_state,
                )

            # Check for error_kind (from model fallback)
            error_kind = attributes.get("error_kind")
            if error_kind:
                return SamplingResult(
                    Decision.RECORD_AND_SAMPLE,
                    attributes=attributes,
                    trace_state=trace_state,
                )

        # Rule 3: Slow requests - 100% sampling
        # Note: Duration is not available at span start, so we check for
        # slow_request attribute that can be set by instrumentation
        if attributes and attributes.get("slow_request"):
            return SamplingResult(
                Decision.RECORD_AND_SAMPLE,
                attributes=attributes,
                trace_state=trace_state,
            )

        # Rule 4: Critical paths - 100% sampling
        for prefix in self.critical_span_prefixes:
            if name.startswith(prefix):
                return SamplingResult(
                    Decision.RECORD_AND_SAMPLE,
                    attributes=attributes,
                    trace_state=trace_state,
                )

        # Rule 5: Normal requests - base rate sampling (10%)
        return self._base_sampler.should_sample(
            parent_context,
            trace_id,
            name,
            kind,
            attributes,
            links,
            trace_state,
        )

    def get_description(self) -> str:
        """Get sampler description."""
        return f"IntelligentSampler(base_rate={self.base_rate}, slow_threshold_ms={self.slow_threshold_ms})"


def create_intelligent_sampler(base_rate: float = 0.1) -> Sampler:
    """Create intelligent sampler with parent-based wrapper.

    Args:
        base_rate: Base sampling rate for normal requests (default: 0.1 = 10%)

    Returns:
        Parent-based intelligent sampler
    """
    if not HAS_OTEL_SDK:
        return None  # type: ignore
    intelligent_sampler = IntelligentSampler(base_rate=base_rate)
    return ParentBased(root=intelligent_sampler)
