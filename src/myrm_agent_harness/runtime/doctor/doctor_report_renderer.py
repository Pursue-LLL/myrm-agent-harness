"""Report renderer synthesizing human-readable Markdown and structured JSON views.

[OUTPUT]
- DoctorReportRenderer: Formats DoctorReport into Markdown dashboards and dictionaries.

[INPUT]
- __future__

[OUTPUT]
- DoctorReportRenderer

[POS]
Report renderer synthesizing human-readable Markdown and structured JSON views.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.doctor.doctor_types import (
    CheckSeverity,
    DoctorCategory,
    DoctorReport,
)

_SEVERITY_ICON_MAP: dict[CheckSeverity, str] = {
    CheckSeverity.PASS: "✅",
    CheckSeverity.WARN: "⚠️",
    CheckSeverity.FAIL: "❌",
    CheckSeverity.INFO: "ℹ️",
}


class DoctorReportRenderer:
    """Renders comprehensive DoctorReport into markdown and serializable structures."""

    @classmethod
    def to_markdown(cls, report: DoctorReport) -> str:
        """Render doctor report as clean GitHub Flavored Markdown."""
        lines: list[str] = [
            "# 🩺 Myrm System Doctor & Capability Verification Report",
            "",
            f"**Overall Status**: {'🟢 HEALTHY' if report.overall_healthy else '🔴 ACTION REQUIRED'} | "
            f"**Passed**: {report.pass_count} | **Warnings**: {report.warn_count} | "
            f"**Failures**: {report.fail_count} | **Duration**: {report.duration_ms:.1f}ms",
            "",
            "---",
        ]

        # Group findings by category
        categories: list[DoctorCategory] = [
            DoctorCategory.CONFIG,
            DoctorCategory.RUNTIME_SANDBOX,
            DoctorCategory.NETWORK_EGRESS,
            DoctorCategory.MODEL,
        ]

        for cat in categories:
            cat_findings = [f for f in report.findings if f.category == cat]
            if not cat_findings:
                continue

            lines.append(f"\n## 📂 {cat.value.upper()} Diagnosis")
            for finding in cat_findings:
                icon = _SEVERITY_ICON_MAP.get(finding.severity, "•")
                lines.append(f"- {icon} **{finding.name}**: {finding.message}")
                if finding.detail:
                    lines.append(f"  - *Detail*: `{finding.detail}`")
                if finding.remediation_hint:
                    lines.append(f"  - *Fix*: {finding.remediation_hint}")

        # Render Capabilities section
        if report.capabilities:
            lines.append("\n## 🛠️ Declared Capability Assertion Consistency")
            for cap in report.capabilities:
                status_icon = "✅" if cap.verified else "❌"
                match_note = (
                    "Consistent" if cap.is_consistent else "FAILED ASSERTION (Declared but Inoperable)"
                )
                lines.append(
                    f"- {status_icon} **{cap.name}** ({cap.kind}) — {match_note} "
                    f"[{cap.latency_ms:.1f}ms]"
                )
                if cap.error_detail:
                    lines.append(f"  - *Error*: `{cap.error_detail}`")

        # Actionable fixes section if failures exist
        failures = [
            f
            for f in report.findings
            if f.severity in (CheckSeverity.FAIL, CheckSeverity.WARN) and f.remediation_hint
        ]
        if failures or any(c for c in report.capabilities if not c.verified):
            lines.append("\n## 💡 Recommended Remediation Steps")
            for idx, item in enumerate(failures, 1):
                auto_tag = " (Auto-fixable)" if item.is_auto_fixable else ""
                lines.append(f"{idx}. **{item.name}**{auto_tag}: {item.remediation_hint}")

        return "\n".join(lines)

    @staticmethod
    def to_dict(report: DoctorReport) -> dict[str, object]:
        """Convert DoctorReport to a JSON-serializable dictionary."""
        return {
            "overall_healthy": report.overall_healthy,
            "pass_count": report.pass_count,
            "warn_count": report.warn_count,
            "fail_count": report.fail_count,
            "duration_ms": report.duration_ms,
            "timestamp": report.timestamp,
            "findings": [
                {
                    "name": f.name,
                    "category": f.category.value,
                    "severity": f.severity.value,
                    "message": f.message,
                    "detail": f.detail,
                    "remediation_hint": f.remediation_hint,
                    "is_auto_fixable": f.is_auto_fixable,
                }
                for f in report.findings
            ],
            "capabilities": [
                {
                    "name": c.name,
                    "kind": c.kind,
                    "declared": c.declared,
                    "verified": c.verified,
                    "is_consistent": c.is_consistent,
                    "latency_ms": c.latency_ms,
                    "error_detail": c.error_detail,
                }
                for c in report.capabilities
            ],
        }
