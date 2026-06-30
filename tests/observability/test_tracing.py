"""Tests for observability/tracing — context, log filter, and JSON formatter."""

from __future__ import annotations

import json
import logging

import pytest

from myrm_agent_harness.observability.tracing import (
    JsonFormatter,
    TracingContext,
    TracingLogFilter,
)


class TestTracingContext:
    def test_default_values(self) -> None:
        assert TracingContext.get_trace_id() == "-"
        assert TracingContext.get_session_id() == "-"

    def test_set_and_reset_trace_id(self) -> None:
        token = TracingContext.set_trace_id("abc-123")
        assert TracingContext.get_trace_id() == "abc-123"
        TracingContext.reset_trace_id(token)
        assert TracingContext.get_trace_id() == "-"

    def test_set_and_reset_session_id(self) -> None:
        token = TracingContext.set_session_id("sess-xyz")
        assert TracingContext.get_session_id() == "sess-xyz"
        TracingContext.reset_session_id(token)
        assert TracingContext.get_session_id() == "-"

    def test_generate_trace_id_format(self) -> None:
        tid = TracingContext.generate_trace_id()
        assert len(tid) == 32
        int(tid, 16)  # must be valid hex

    def test_generate_trace_id_uniqueness(self) -> None:
        ids = {TracingContext.generate_trace_id() for _ in range(100)}
        assert len(ids) == 100

    def test_nested_set_and_reset(self) -> None:
        token_outer = TracingContext.set_trace_id("outer")
        token_inner = TracingContext.set_trace_id("inner")
        assert TracingContext.get_trace_id() == "inner"
        TracingContext.reset_trace_id(token_inner)
        assert TracingContext.get_trace_id() == "outer"
        TracingContext.reset_trace_id(token_outer)
        assert TracingContext.get_trace_id() == "-"


class TestTracingLogFilter:
    def test_injects_trace_and_session(self) -> None:
        trace_token = TracingContext.set_trace_id("t-001")
        session_token = TracingContext.set_session_id("s-001")
        try:
            record = logging.LogRecord(
                name="test", level=logging.INFO, pathname="",
                lineno=0, msg="hello", args=(), exc_info=None,
            )
            flt = TracingLogFilter()
            assert flt.filter(record) is True
            assert record.trace_id == "t-001"  # type: ignore[attr-defined]
            assert record.session_id == "s-001"  # type: ignore[attr-defined]
        finally:
            TracingContext.reset_trace_id(trace_token)
            TracingContext.reset_session_id(session_token)

    def test_defaults_when_no_context(self) -> None:
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="",
            lineno=0, msg="hello", args=(), exc_info=None,
        )
        flt = TracingLogFilter()
        flt.filter(record)
        assert record.trace_id == "-"  # type: ignore[attr-defined]
        assert record.session_id == "-"  # type: ignore[attr-defined]

    def test_filter_is_idempotent(self) -> None:
        token = TracingContext.set_trace_id("idem-001")
        try:
            record = logging.LogRecord(
                name="test", level=logging.INFO, pathname="",
                lineno=0, msg="msg", args=(), exc_info=None,
            )
            flt = TracingLogFilter()
            flt.filter(record)
            flt.filter(record)
            assert record.trace_id == "idem-001"  # type: ignore[attr-defined]
        finally:
            TracingContext.reset_trace_id(token)


class TestJsonFormatter:
    def test_output_is_valid_json(self) -> None:
        record = logging.LogRecord(
            name="test.logger", level=logging.WARNING, pathname="",
            lineno=0, msg="danger %s", args=("zone",), exc_info=None,
        )
        record.trace_id = "deadbeef"  # type: ignore[attr-defined]
        record.session_id = "s-42"  # type: ignore[attr-defined]

        formatter = JsonFormatter()
        output = formatter.format(record)
        data = json.loads(output)

        assert data["level"] == "WARNING"
        assert data["logger"] == "test.logger"
        assert data["trace_id"] == "deadbeef"
        assert data["session_id"] == "s-42"
        assert data["message"] == "danger zone"
        assert "timestamp" in data

    def test_exception_included(self) -> None:
        import sys

        try:
            raise ValueError("boom")
        except ValueError:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test", level=logging.ERROR, pathname="",
            lineno=0, msg="failed", args=(), exc_info=exc_info,
        )
        record.trace_id = "-"  # type: ignore[attr-defined]
        record.session_id = "-"  # type: ignore[attr-defined]

        formatter = JsonFormatter()
        data = json.loads(formatter.format(record))
        assert "exception" in data
        assert "ValueError: boom" in data["exception"]

    def test_fallback_when_no_trace_attrs(self) -> None:
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="",
            lineno=0, msg="no ctx", args=(), exc_info=None,
        )
        formatter = JsonFormatter()
        data = json.loads(formatter.format(record))
        assert data["trace_id"] == "-"
        assert data["session_id"] == "-"

    def test_exc_info_boolean_true_handled(self) -> None:
        record = logging.LogRecord(
            name="test", level=logging.ERROR, pathname="",
            lineno=0, msg="fail", args=(), exc_info=True,
        )
        record.trace_id = "-"  # type: ignore[attr-defined]
        record.session_id = "-"  # type: ignore[attr-defined]
        formatter = JsonFormatter()
        data = json.loads(formatter.format(record))
        assert "exception" not in data

    def test_redaction_applied(self) -> None:
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="",
            lineno=0, msg="key=sk-proj-abc123def456ghi789jkl012", args=(),
            exc_info=None,
        )
        record.trace_id = "-"  # type: ignore[attr-defined]
        record.session_id = "-"  # type: ignore[attr-defined]
        formatter = JsonFormatter()
        data = json.loads(formatter.format(record))
        assert "sk-proj-abc123def456ghi789jkl012" not in data["message"]
