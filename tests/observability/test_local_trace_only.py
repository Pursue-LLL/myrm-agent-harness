"""Tests for the local-trace-only isolation gate."""

from __future__ import annotations

import pytest

from myrm_agent_harness.infra.tracing import (
    assert_local_trace_only,
    is_local_trace_only,
    setup_tracing,
)


def test_is_local_trace_only_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MYRM_LOCAL_TRACE_ONLY", raising=False)
    assert not is_local_trace_only()

    for val in ("1", "true", "True", "yes", "YES", "on"):
        monkeypatch.setenv("MYRM_LOCAL_TRACE_ONLY", val)
        assert is_local_trace_only()

    for val in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("MYRM_LOCAL_TRACE_ONLY", val)
        assert not is_local_trace_only()


def test_assert_local_trace_only_blocks_remote_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYRM_LOCAL_TRACE_ONLY", "1")

    # Local endpoints are safe
    assert_local_trace_only(None)
    assert_local_trace_only("http://localhost:4317")
    assert_local_trace_only("http://127.0.0.1:4318")
    assert_local_trace_only("grpc://localhost:4317")

    # Remote endpoints must raise PermissionError
    with pytest.raises(PermissionError) as exc_info:
        assert_local_trace_only("https://otlp.datadoghq.com")
    assert "Remote trace export" in str(exc_info.value)
    assert "blocked in local-trace-only mode" in str(exc_info.value)

    with pytest.raises(PermissionError):
        assert_local_trace_only("grpc://collector.internal.corp:4317")


def test_setup_tracing_enforces_local_trace_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYRM_LOCAL_TRACE_ONLY", "1")

    # Attempting to setup tracing with a remote endpoint should fail-closed
    with pytest.raises(PermissionError):
        setup_tracing(
            service_name="test-service",
            otlp_endpoint="https://external-jaeger.com:4317",
            local_trace_only=True,
        )
