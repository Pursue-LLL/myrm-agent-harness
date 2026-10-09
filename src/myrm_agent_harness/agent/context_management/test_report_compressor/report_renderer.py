"""Failure-first compact summary renderer for normalized test execution reports.

[INPUT]
- report_compressor_types: NormalizedTestReport, TestReportCompressorConfig.

[OUTPUT]
- FailureFirstSummaryRenderer: Renders a high-density, failure-prioritized text summary.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.test_report_compressor
- Module: report_renderer.py
"""

from typing import List

from myrm_agent_harness.agent.context_management.test_report_compressor.report_compressor_types import (
    NormalizedTestReport,
    TestReportCompressorConfig,
)


class FailureFirstSummaryRenderer:
    """Renders normalized test reports into clean, failure-first compact text."""

    @staticmethod
    def render(
        report: NormalizedTestReport,
        config: TestReportCompressorConfig,
    ) -> str:
        """Formats normalized report into standardized summary string.

        Args:
            report: Normalized intermediate test representation.
            config: Compression and formatting configuration.

        Returns:
            Concise text representation prioritizing failures and bounded stack traces.
        """
        lines: List[str] = []

        # 1. Summary line
        summary_parts: List[str] = []
        if report.passed > 0:
            summary_parts.append(f"{report.passed} passed")
        if report.failed > 0:
            summary_parts.append(f"{report.failed} failed")
        if report.errors > 0:
            summary_parts.append(f"{report.errors} errors")
        if report.skipped > 0:
            summary_parts.append(f"{report.skipped} skipped")

        for name, count in sorted(report.other_counts.items()):
            if count > 0:
                summary_parts.append(f"{count} {name}")

        stats_str = ", ".join(summary_parts) if summary_parts else "0 tests"
        duration_str = f" ({report.duration_seconds:.1f}s)" if report.duration_seconds > 0 else ""
        lines.append(f"TEST SUMMARY: {stats_str}{duration_str}")

        # 2. Detailed failures and errors
        for failure in report.failures:
            lines.append("")
            label = "ERROR" if failure.failure_type == "error" else "FAILED"
            lines.append(f"{label}: {failure.name}")

            # Indent error message
            msg = failure.message.strip()
            if msg:
                msg_lines = msg.splitlines()
                if len(msg_lines) > config.max_failure_message_lines:
                    msg_lines = msg_lines[: config.max_failure_message_lines] + [
                        f"... ({len(msg_lines) - config.max_failure_message_lines} message lines omitted)"
                    ]
                for m_line in msg_lines:
                    lines.append(f"  {m_line}")

            # Indent stack frames
            for frame in failure.stack_frames:
                lines.append(f"  {frame}")

        return "\n".join(lines)
