"""Runtime diagnostics tool.

[INPUT]
- myrm_agent_harness.observability.diagnostics::run_all_diagnostics (POS: framework health probe runner)
- langchain.tools::tool (POS: LangChain tool decorator)

[OUTPUT]
- runtime_diagnostics_tool: read-only LangChain tool returning structured health data

[POS]
Framework-level read-only diagnostics tool. It exposes existing Harness health
probes to agents without coupling to product UI, business repair actions, or
control-plane concepts.
"""

from __future__ import annotations

from langchain.tools import tool
from pydantic import BaseModel, Field

from myrm_agent_harness.observability.diagnostics import run_all_diagnostics


class RuntimeDiagnosticsInput(BaseModel):
    """Input for runtime diagnostics."""

    include_passed: bool = Field(
        default=False,
        description="Whether to include passing components. Defaults to false to keep output concise.",
    )


def _user_summary(status_counts: dict[str, int]) -> str:
    fail_count = status_counts.get("fail", 0)
    warn_count = status_counts.get("warn", 0)
    if fail_count > 0:
        return f"{fail_count} failing runtime component(s) need attention."
    if warn_count > 0:
        return f"{warn_count} runtime component(s) reported warnings."
    return "Runtime diagnostics passed."


@tool("runtime_diagnostics_tool", args_schema=RuntimeDiagnosticsInput)
async def runtime_diagnostics_tool(include_passed: bool = False) -> dict[str, object]:
    """Run read-only runtime diagnostics for the current agent environment.

    Use this when the user asks why the agent/runtime is failing, slow, unable
    to save files, unable to retrieve memory, or otherwise appears unhealthy.
    This tool does not repair anything and does not expose secrets.
    """

    reports = await run_all_diagnostics()
    status_counts: dict[str, int] = {"pass": 0, "warn": 0, "fail": 0}
    components: list[dict[str, str | None]] = []

    for report in reports:
        normalized_status = report.status.lower()
        if normalized_status not in status_counts:
            normalized_status = "warn"
        status_counts[normalized_status] += 1

        if include_passed or normalized_status != "pass":
            entry: dict[str, str | None] = {
                "component_name": report.component_name,
                "status": normalized_status,
                "message": report.message,
                "detail": report.detail,
                "fix_suggestion": report.fix_suggestion,
            }
            components.append(entry)

    overall_status = "fail" if status_counts["fail"] else "warn" if status_counts["warn"] else "pass"
    return {
        "overall_status": overall_status,
        "summary": _user_summary(status_counts),
        "status_counts": status_counts,
        "components": components,
        "read_only": True,
    }
