"""Browser Doctor — report types and CLI rendering.

Defines the diagnostic result data model (``CheckStatus`` / ``DoctorCheckResult`` /
``DoctorReport``) and the colored CLI renderer for doctor output.

[INPUT]
- CheckStatus/DoctorCheckResult/DoctorReport produced by .checks and .orphans

[OUTPUT]
- CheckStatus: status enum (ok/warning/error/missing)
- DoctorCheckResult: single check result (name/status/message/fix/details)
- DoctorReport: aggregated report (checks/summary/overall_healthy/recommendations)
- format_report: colored CLI rendering

[POS]
Doctor data models and CLI presentation. Kept framework-agnostic so both the
harness CLI and server health endpoints can consume the same report contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class CheckStatus(StrEnum):
    """Status of a diagnostic check."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class DoctorCheckResult:
    """Result of a single diagnostic check."""

    name: str
    status: CheckStatus
    message: str
    fix: str | None = None
    details: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """Complete diagnostic report."""

    checks: dict[str, DoctorCheckResult]
    summary: str
    overall_healthy: bool
    recommendations: list[str] = field(default_factory=list)


def _status_icon(status: CheckStatus, green: str, yellow: str, red: str) -> str:
    """Get colored status icon."""
    if status == CheckStatus.OK:
        return green
    if status == CheckStatus.WARNING:
        return f"{yellow}·"
    return red


def format_report(report: DoctorReport) -> str:
    """Render doctor report as colored CLI output.

    Args:
        report: DoctorReport to render

    Returns:
        Formatted string with ANSI color codes
    """
    try:
        import colorama

        colorama.init()
        green = "\033[92m"
        yellow = "\033[93m"
        red = "\033[91m"
        blue = "\033[94m"
        bold = "\033[1m"
        reset = "\033[0m"
    except (ImportError, TypeError):
        green = yellow = red = blue = bold = reset = ""

    lines = [f"{bold} Browser Doctor{reset}", ""]

    lines.append(f"{bold}Environment{reset}")
    for name in [
        "patchright",
        "camoufox",
        "memory",
        "disk",
        "proxy",
    ]:
        if name in report.checks:
            check = report.checks[name]
            icon = _status_icon(check.status, green, yellow, red)
            lines.append(f"  {icon} {check.message}")
            if check.fix:
                lines.append(f"    {blue}Fix: {check.fix}{reset}")

    if "orphan_processes" in report.checks:
        lines.append("")
        lines.append(f"{bold}Process Cleanup{reset}")
        check = report.checks["orphan_processes"]
        icon = _status_icon(check.status, green, yellow, red)
        lines.append(f"  {icon} {check.message}")
        if check.fix:
            lines.append(f"    {blue}Fix: {check.fix}{reset}")

    if "extension_relay" in report.checks:
        lines.append("")
        lines.append(f"{bold}Extension Relay{reset}")
        check = report.checks["extension_relay"]
        icon = _status_icon(check.status, green, yellow, red)
        lines.append(f"  {icon} {check.message}")
        if check.fix:
            lines.append(f"    {blue}Fix: {check.fix}{reset}")

    if "browser_launch" in report.checks:
        lines.append("")
        lines.append(f"{bold}Launch Test{reset}")
        check = report.checks["browser_launch"]
        icon = _status_icon(check.status, green, yellow, red)
        lines.append(f"  {icon} {check.message}")
        if check.fix:
            lines.append(f"    {blue}Fix: {check.fix}{reset}")

    if report.recommendations:
        lines.append("")
        lines.append(f"{bold}Recommendations{reset}")
        for i, rec in enumerate(report.recommendations, 1):
            lines.append(f"  {i}. {rec}")

    lines.append("")
    if report.overall_healthy:
        lines.append(f"{green}{bold}Status: All checks passed {reset}")
    else:
        lines.append(f"{red}{bold}Status: {report.summary}{reset}")

    return "\n".join(lines)
