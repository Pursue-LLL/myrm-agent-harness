"""[INPUT]
- (none)

[OUTPUT]
- HealthReport: Component health status report.
- DiagnosticProtocol: Diagnostic protocol interface.
- redact_health_report: Redact sensitive information from health reports.

[POS]
Provides HealthReport, DiagnosticProtocol, redact_health_report.
"""

import re
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

_REDACT_PATTERN = re.compile(r"[A-Za-z0-9_./+=:-]{32,}")
_SENSITIVE_KEYS = frozenset({
    "api_key", "apikey", "api-key", "access_token", "accesstoken",
    "refresh_token", "refreshtoken", "secret", "password", "passwd",
    "authorization", "bearer", "token", "credential", "private_key",
})

HealthStatus = Literal["pass", "warn", "fail"]


class HealthReport(BaseModel):
    """Component health status report.

    ``message`` is a **user-friendly** summary shown in the GUI.
    ``detail`` carries the raw technical context (exception text, metric
    values, etc.) that developers can expand to inspect.
    ``measured`` / ``expected`` / ``cause`` provide structured issue metadata
    for actionable diagnostics (inspired by codex-cli DoctorIssue).
    """

    component_name: str = Field(..., description="Component name, e.g. 'BrowserToolkit'")
    status: HealthStatus = Field(..., description="Status: 'pass', 'warn', or 'fail'")
    message: str = Field(..., description="User-friendly status summary shown in the GUI")
    code: str | None = Field(default=None, description="Structured error or status code for multi-language i18n mapping")
    meta_data: dict[str, object] | None = Field(default=None, description="Structured metadata corresponding to the code")
    detail: str | None = Field(default=None, description="Technical detail for developers (expandable in the dashboard)")
    fix_suggestion: str | None = Field(default=None, description="User-facing fix suggestion")
    metrics: dict[str, float] | None = Field(default=None, description="Optional quantitative metrics (e.g., latency, throughput) for performance benchmarks")
    measured: str | None = Field(default=None, description="Actual measured value when check fails (e.g., 'HTTP 404', 'Memory 95%')")
    expected: str | None = Field(default=None, description="Expected value for a healthy state (e.g., 'HTTP 200', 'Memory <80%')")
    cause: str | None = Field(default=None, description="Root cause description explaining why the check failed")


@runtime_checkable
class DiagnosticProtocol(Protocol):
    """Diagnostic protocol interface.

    Any toolkit or module that wishes to expose its health status should
    implement this interface and register via ``manager.register_protocol``.
    """

    async def check_health(self) -> HealthReport:
        """Run self-check and return a health status report."""
        ...


def _redact_value(key: str, value: str) -> str:
    """Redact a value if its key suggests sensitive content."""
    if any(sensitive in key.lower() for sensitive in _SENSITIVE_KEYS):
        return "<redacted>"
    return _REDACT_PATTERN.sub("<redacted>", value)


def redact_health_report(report: HealthReport) -> HealthReport:
    """Return a copy of the report with sensitive information redacted.

    Redacts:
    - API keys, tokens, secrets in detail/fix_suggestion fields
    - Long alphanumeric strings that look like secrets (32+ chars)
    """
    redacted_detail = None
    if report.detail:
        redacted_detail = _REDACT_PATTERN.sub("<redacted>", report.detail)

    redacted_fix = None
    if report.fix_suggestion:
        redacted_fix = _REDACT_PATTERN.sub("<redacted>", report.fix_suggestion)

    redacted_meta = None
    if report.meta_data:
        redacted_meta = {}
        for k, v in report.meta_data.items():
            if isinstance(v, str):
                redacted_meta[k] = _redact_value(k, v)
            else:
                redacted_meta[k] = v

    return HealthReport(
        component_name=report.component_name,
        status=report.status,
        message=report.message,
        code=report.code,
        meta_data=redacted_meta,
        detail=redacted_detail,
        fix_suggestion=redacted_fix,
        metrics=report.metrics,
        measured=report.measured,
        expected=report.expected,
        cause=report.cause,
    )
