"""Tests for myrm_agent_harness.infra.tracing.propagation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from opentelemetry.context import Context

from myrm_agent_harness.infra.tracing.propagation import (
    extract_trace_context,
    get_current_span_id,
    get_current_trace_id,
    inject_trace_context,
)


def test_inject_trace_context_creates_carrier() -> None:
    with patch("myrm_agent_harness.infra.tracing.propagation.propagate.inject") as mock_inject:
        out = inject_trace_context(None)
    assert out == {}
    mock_inject.assert_called_once_with(out)


def test_inject_trace_context_reuses_carrier() -> None:
    carrier: dict[str, str] = {"x": "1"}
    with patch("myrm_agent_harness.infra.tracing.propagation.propagate.inject") as mock_inject:
        out = inject_trace_context(carrier)
    assert out is carrier
    mock_inject.assert_called_once_with(carrier)


def test_extract_trace_context() -> None:
    carrier: dict[str, str] = {"traceparent": "00-..."}
    ctx = Context()
    with patch(
        "myrm_agent_harness.infra.tracing.propagation.propagate.extract",
        return_value=ctx,
    ) as mock_extract:
        got = extract_trace_context(carrier)
    assert got is ctx
    mock_extract.assert_called_once_with(carrier)


def test_get_current_trace_and_span_ids_with_active_span() -> None:
    mock_span = MagicMock()
    mock_span.get_span_context.return_value.trace_id = 0xAB
    mock_span.get_span_context.return_value.span_id = 0xCD
    mock_span.get_span_context.return_value.is_valid = True
    with patch("myrm_agent_harness.infra.tracing.propagation.trace.get_current_span", return_value=mock_span):
        tid = get_current_trace_id()
        sid = get_current_span_id()
    assert tid == format(0xAB, "032x")
    assert sid == format(0xCD, "016x")


def test_get_current_trace_and_span_ids_no_valid_span() -> None:
    mock_span = MagicMock()
    mock_span.get_span_context.return_value.is_valid = False
    with patch("myrm_agent_harness.infra.tracing.propagation.trace.get_current_span", return_value=mock_span):
        assert get_current_trace_id() is None
        assert get_current_span_id() is None
