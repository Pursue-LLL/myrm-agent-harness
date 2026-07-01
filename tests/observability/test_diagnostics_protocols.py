"""Tests for observability diagnostics protocols.

Covers:
- HealthReport: model creation, fields, validation
- redact_health_report: sensitive data redaction patterns
- DiagnosticProtocol: runtime_checkable behavior
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.observability.diagnostics.protocols import (
    DiagnosticProtocol,
    HealthReport,
    redact_health_report,
)


class TestHealthReport:
    def test_minimal_creation(self):
        report = HealthReport(component_name="Test", status="pass", message="All good")
        assert report.component_name == "Test"
        assert report.status == "pass"
        assert report.message == "All good"
        assert report.detail is None
        assert report.fix_suggestion is None

    def test_full_creation(self):
        report = HealthReport(
            component_name="DB",
            status="fail",
            message="Database down",
            code="DB_CONN_FAIL",
            meta_data={"retries": 3},
            detail="Connection refused on port 5432",
            fix_suggestion="Restart PostgreSQL",
            metrics={"latency_ms": 5000.0},
            measured="timeout after 5s",
            expected="response <1s",
            cause="Database process crashed",
        )
        assert report.code == "DB_CONN_FAIL"
        assert report.meta_data == {"retries": 3}
        assert report.metrics == {"latency_ms": 5000.0}
        assert report.measured == "timeout after 5s"
        assert report.expected == "response <1s"
        assert report.cause == "Database process crashed"

    def test_status_validation(self):
        for status in ("pass", "warn", "fail"):
            report = HealthReport(component_name="X", status=status, message="m")
            assert report.status == status

    def test_serialization_roundtrip(self):
        report = HealthReport(
            component_name="Net",
            status="warn",
            message="High latency",
            detail="p99=500ms",
        )
        data = report.model_dump()
        restored = HealthReport(**data)
        assert restored == report


class TestRedactHealthReport:
    def test_redacts_long_strings_in_detail(self):
        secret = "a" * 40
        report = HealthReport(
            component_name="Test",
            status="fail",
            message="Error",
            detail=f"API key: {secret}",
        )
        redacted = redact_health_report(report)
        assert secret not in redacted.detail
        assert "<redacted>" in redacted.detail

    def test_redacts_long_strings_in_fix_suggestion(self):
        token = "sk_live_" + "x" * 40
        report = HealthReport(
            component_name="Test",
            status="fail",
            message="Error",
            fix_suggestion=f"Use token {token} to authenticate",
        )
        redacted = redact_health_report(report)
        assert token not in redacted.fix_suggestion
        assert "<redacted>" in redacted.fix_suggestion

    def test_redacts_sensitive_meta_data_keys(self):
        report = HealthReport(
            component_name="Test",
            status="fail",
            message="Error",
            meta_data={
                "api_key": "secret123",
                "component": "auth",
                "access_token": "bearer_xyz",
            },
        )
        redacted = redact_health_report(report)
        assert redacted.meta_data["api_key"] == "<redacted>"
        assert redacted.meta_data["component"] == "auth"
        assert redacted.meta_data["access_token"] == "<redacted>"

    def test_preserves_short_non_sensitive_strings(self):
        report = HealthReport(
            component_name="Test",
            status="pass",
            message="OK",
            detail="Port 8080 is open",
        )
        redacted = redact_health_report(report)
        assert redacted.detail == "Port 8080 is open"

    def test_preserves_non_string_meta_values(self):
        report = HealthReport(
            component_name="Test",
            status="pass",
            message="OK",
            meta_data={"count": 42, "enabled": True},
        )
        redacted = redact_health_report(report)
        assert redacted.meta_data["count"] == 42
        assert redacted.meta_data["enabled"] is True

    def test_none_fields_stay_none(self):
        report = HealthReport(component_name="Test", status="pass", message="OK")
        redacted = redact_health_report(report)
        assert redacted.detail is None
        assert redacted.fix_suggestion is None
        assert redacted.meta_data is None

    def test_message_is_never_redacted(self):
        long_msg = "A" * 50
        report = HealthReport(component_name="Test", status="pass", message=long_msg)
        redacted = redact_health_report(report)
        assert redacted.message == long_msg


class TestDiagnosticProtocol:
    def test_runtime_checkable(self):
        class ValidDiagnostic:
            async def check_health(self) -> HealthReport:
                return HealthReport(component_name="V", status="pass", message="ok")

        assert isinstance(ValidDiagnostic(), DiagnosticProtocol)

    def test_invalid_class_not_instance(self):
        class InvalidDiagnostic:
            def do_something(self) -> None:
                pass

        assert not isinstance(InvalidDiagnostic(), DiagnosticProtocol)
