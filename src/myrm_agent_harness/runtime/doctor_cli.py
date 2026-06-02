"""CLI Formatter for Myrm Doctor.

Separates diagnostic logic from UI presentation.

[INPUT]
- toolkits.browser.doctor::CheckStatus, DoctorReport (POS: Browser toolkit diagnostics module. Validates dependencies, configuration, environment, and browser launchability before actual operations. Provides clear fix suggestions for each failure. Includes precise orphan process detection (matches patchright/playwright cache paths) with safety mechanisms (dry-run default, force flag required for cleanup).)

[OUTPUT]
- format_styled_report: function — format_styled_report

[POS]
CLI Formatter for Myrm Doctor.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.browser.doctor import CheckStatus, DoctorReport


class _Colors:
    def __init__(self) -> None:
        try:
            import colorama

            colorama.init()
            self.green = "\033[92m"
            self.yellow = "\033[93m"
            self.red = "\033[91m"
            self.blue = "\033[94m"
            self.bold = "\033[1m"
            self.reset = "\033[0m"
        except (ImportError, TypeError):
            self.green = self.yellow = self.red = self.blue = self.bold = self.reset = ""

    def status_icon(self, status: CheckStatus) -> str:
        if status == CheckStatus.OK:
            return f"{self.green}"
        if status == CheckStatus.WARNING:
            return f"{self.yellow}·"
        return f"{self.red}"


def format_styled_report(report: DoctorReport) -> str:
    c = _Colors()
    lines = [f"{c.bold} Myrm Agent Harness Diagnostic Report{c.reset}", ""]

    # Grouping
    sys_checks = []
    dep_checks = []
    llm_checks = []
    browser_checks = []

    for name, check in report.checks.items():
        if name in ("python", "core_deps") or name.startswith("opt_"):
            dep_checks.append(check)
        elif name in ("memory", "disk"):
            sys_checks.append(check)
        elif name.startswith("llm_"):
            llm_checks.append(check)
        else:
            browser_checks.append(check)

    groups = [
        ("Environment & Dependencies", dep_checks),
        ("System Resources", sys_checks),
        ("LLM Connectivity", llm_checks),
        ("Browser & Automation", browser_checks),
    ]

    for title, items in groups:
        if not items:
            continue
        lines.append(f"{c.bold}{title}{c.reset}")
        for item in items:
            icon = c.status_icon(item.status)
            lines.append(f" {icon} {item.message}{c.reset}")
            if item.fix and item.status != CheckStatus.OK:
                lines.append(f" {c.blue} Fix: {item.fix}{c.reset}")
        lines.append("")

    if report.recommendations:
        lines.append(f"{c.bold}Summary Recommendations{c.reset}")
        for i, rec in enumerate(report.recommendations, 1):
            lines.append(f" {i}. {rec}")
        lines.append("")

    status_color = c.green if report.overall_healthy else c.red
    lines.append(f"{status_color}{c.bold}Status: {report.summary}{c.reset}")

    return "\n".join(lines)
