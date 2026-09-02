"""Structured export formatters (JSON, CSV, Markdown) for Compliance Audit Trails.

[INPUT]
- types::(AuditTrailEntry, ComplianceReport, AuditSummaryStats)
- redactor::compute_redaction_fingerprint
- json, csv, io, datetime

[OUTPUT]
- ComplianceTrailExporter: Generates structured compliance export artifacts

[POS]
Harness-level exporter providing enterprise-ready zero-leakage compliance packages.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timezone
from typing import Sequence

from myrm_agent_harness.observability.audit_trail.collector import DualTrackAuditCollector
from myrm_agent_harness.observability.audit_trail.redactor import compute_redaction_fingerprint
from myrm_agent_harness.observability.audit_trail.types import ComplianceReport


class ComplianceTrailExporter:
    """Exports dual-track audit trail entries to structured JSON, CSV, and Markdown dossiers."""

    @classmethod
    def generate_report(
        cls,
        collector: DualTrackAuditCollector,
        *,
        session_id: str | None = None,
        agent_id: str | None = None,
        time_window_hours: int = 24,
    ) -> ComplianceReport:
        """Construct an immutable ComplianceReport dossier."""
        entries = collector.list_entries(session_id=session_id, agent_id=agent_id, limit=5000)
        summary = collector.get_summary_stats(session_id=session_id, agent_id=agent_id)

        raw_str = f"{len(entries)}:{summary.compliance_rate}:{datetime.now(timezone.utc).isoformat()}"
        fp = compute_redaction_fingerprint(raw_str)

        return ComplianceReport(
            report_id=f"rep_{uuid.uuid4().hex[:12]}",
            generated_at=datetime.now(timezone.utc).isoformat(),
            time_window_hours=time_window_hours,
            summary=summary,
            entries=entries,
            export_redaction_fingerprint=fp,
        )

    @classmethod
    def export_json(cls, report: ComplianceReport) -> str:
        """Export compliance report as indented JSON."""
        data = {
            "report_id": report.report_id,
            "generated_at": report.generated_at,
            "time_window_hours": report.time_window_hours,
            "fingerprint": report.export_redaction_fingerprint,
            "summary": {
                "total_entries": report.summary.total_entries,
                "permitted_count": report.summary.permitted_count,
                "refused_count": report.summary.refused_count,
                "failed_count": report.summary.failed_count,
                "human_take_the_wheel_count": report.summary.human_take_the_wheel_count,
                "compliance_rate": report.summary.compliance_rate,
                "avg_latency_ms": report.summary.avg_latency_ms,
                "top_rules_triggered": [
                    {
                        "rule_name": r.rule_name,
                        "trigger_count": r.trigger_count,
                        "refused_count": r.refused_count,
                        "permitted_count": r.permitted_count,
                        "failed_count": r.failed_count,
                        "refusal_rate": r.refusal_rate,
                        "sample_targets": list(r.sample_targets),
                    }
                    for r in report.summary.top_rules_triggered
                ],
            },
            "entries": [
                {
                    "entry_id": e.entry_id,
                    "session_id": e.session_id,
                    "agent_id": e.agent_id,
                    "tool_name": e.tool_name,
                    "intent_summary": e.intent_summary,
                    "raw_intent_args": dict(e.raw_intent_args),
                    "rule_name": e.rule_name,
                    "state": str(e.state),
                    "outcome": str(e.outcome),
                    "is_human_take_the_wheel": e.is_human_take_the_wheel,
                    "created_at": e.created_at.isoformat(),
                    "completed_at": e.completed_at.isoformat() if e.completed_at else None,
                    "latency_ms": e.latency_ms,
                    "output_length": e.output_length,
                    "error_message": e.error_message,
                }
                for e in report.entries
            ],
        }
        return json.dumps(data, indent=2, ensure_ascii=False)

    @classmethod
    def export_csv(cls, report: ComplianceReport) -> str:
        """Export compliance report entries as standard CSV."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "entry_id",
            "created_at",
            "session_id",
            "agent_id",
            "tool_name",
            "intent_summary",
            "rule_name",
            "state",
            "outcome",
            "is_human_take_the_wheel",
            "latency_ms",
            "output_length",
            "error_message",
        ])

        for e in report.entries:
            writer.writerow([
                e.entry_id,
                e.created_at.isoformat(),
                e.session_id,
                e.agent_id,
                e.tool_name,
                e.intent_summary,
                e.rule_name,
                str(e.state),
                str(e.outcome),
                "YES" if e.is_human_take_the_wheel else "NO",
                e.latency_ms,
                e.output_length,
                e.error_message or "",
            ])

        return output.getvalue()

    @classmethod
    def export_markdown(cls, report: ComplianceReport) -> str:
        """Export compliance dossier as structured Markdown."""
        lines: list[str] = [
            f"# Enterprise Compliance & Audit Trail Dossier",
            f"",
            f"- **Report ID**: `{report.report_id}`",
            f"- **Generated At**: `{report.generated_at}`",
            f"- **Verification Seal**: `{report.export_redaction_fingerprint}`",
            f"- **Compliance Pass Rate**: `{report.summary.compliance_rate:.1%}`",
            f"- **Total Action Events**: `{report.summary.total_entries}`",
            f"- **Permitted / Refused / Failed**: `{report.summary.permitted_count}` / `{report.summary.refused_count}` / `{report.summary.failed_count}`",
            f"- **Human Take-The-Wheel Interceptions**: `{report.summary.human_take_the_wheel_count}`",
            f"",
            f"## Security Policy & Rule Interceptions",
            f"",
            f"| Rule Name | Total Hits | Refused | Permitted | Failed | Refusal Rate |",
            f"|-----------|------------|---------|-----------|--------|--------------|",
        ]

        for r in report.summary.top_rules_triggered:
            lines.append(
                f"| `{r.rule_name}` | {r.trigger_count} | {r.refused_count} | {r.permitted_count} | {r.failed_count} | {r.refusal_rate:.1%} |"
            )

        lines.extend([
            f"",
            f"## Recent Audit Trail Log Entries (Redacted & Sealed)",
            f"",
            f"| Time | Session | Tool | State | Outcome | Rule | TTW | Latency | Summary |",
            f"|------|---------|------|-------|---------|------|-----|---------|---------|",
        ])

        for e in report.entries[:50]:
            ttw_tag = "🧑 TakeWheel" if e.is_human_take_the_wheel else "🤖 Auto"
            ts = e.created_at.strftime("%H:%M:%S")
            lines.append(
                f"| {ts} | `{e.session_id[:8]}` | `{e.tool_name}` | `{e.state}` | `{e.outcome}` | `{e.rule_name}` | {ttw_tag} | {e.latency_ms}ms | {e.intent_summary} |"
            )

        return "\n".join(lines)
