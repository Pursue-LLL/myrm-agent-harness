"""Tests for myrm_agent_harness.infra.tracing.sampling."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from opentelemetry.sdk.trace.sampling import Decision, ParentBased, SamplingResult
from opentelemetry.trace import SpanContext, SpanKind, TraceFlags

from myrm_agent_harness.infra.tracing.sampling import IntelligentSampler, create_intelligent_sampler


def _sampled_parent() -> SpanContext:
    return SpanContext(
        trace_id=0x12345678901234567890123456789012,
        span_id=0x1234567890123456,
        is_remote=False,
        trace_flags=TraceFlags(0x01),
    )


def test_should_sample_parent_sampled() -> None:
    sampler = IntelligentSampler(base_rate=0.0)
    parent = _sampled_parent()
    result = sampler.should_sample(
        parent,
        0x12345678901234567890123456789012,
        "child",
        SpanKind.INTERNAL,
        None,
        None,
        None,
    )
    assert result.decision == Decision.RECORD_AND_SAMPLE


@pytest.mark.parametrize(
    ("attrs", "name"),
    [
        ({"error": True}, "x"),
        ({"exception": "e"}, "x"),
        ({"status": "failed"}, "x"),
        ({"error_kind": "timeout"}, "x"),
        ({"slow_request": True}, "x"),
    ],
)
def test_should_sample_error_and_slow_and_status(attrs: dict[str, object], name: str) -> None:
    sampler = IntelligentSampler(base_rate=0.0)
    result = sampler.should_sample(None, 1, name, SpanKind.INTERNAL, attrs, None, None)
    assert result.decision == Decision.RECORD_AND_SAMPLE


@pytest.mark.parametrize(
    "span_name",
    ["model_fallback_invoke", "delivery_send", "llm_call_openai"],
)
def test_should_sample_critical_prefixes(span_name: str) -> None:
    sampler = IntelligentSampler(base_rate=0.0)
    result = sampler.should_sample(None, 1, span_name, SpanKind.INTERNAL, None, None, None)
    assert result.decision == Decision.RECORD_AND_SAMPLE


def test_should_sample_normal_delegates_to_base_sampler() -> None:
    sampler = IntelligentSampler(base_rate=0.0)
    mock_base = MagicMock()
    mock_base.should_sample.return_value = SamplingResult(Decision.DROP, None, None)
    sampler._base_sampler = mock_base  # type: ignore[method-assign]
    result = sampler.should_sample(None, 1, "normal_span", SpanKind.INTERNAL, None, None, None)
    assert result.decision == Decision.DROP
    mock_base.should_sample.assert_called_once()


def test_get_description() -> None:
    sampler = IntelligentSampler(base_rate=0.2, slow_threshold_ms=500.0)
    text = sampler.get_description()
    assert "IntelligentSampler" in text
    assert "0.2" in text
    assert "500.0" in text


def test_create_intelligent_sampler_returns_parent_based() -> None:
    root = create_intelligent_sampler(base_rate=0.1)
    assert isinstance(root, ParentBased)
