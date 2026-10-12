"""Browser Doctor — orphan process check adapter.

Turns the orphan process scan and the dry-run stale sandbox scan into one doctor
check result, so ``orphans`` stays free of the report data model.

[INPUT]
- .orphans::find_orphan_automation_processes (POS: orphan process detection)
- .sandboxes::cleanup_stale_automation_sandboxes (POS: dry-run-first stale sandbox prune)
- .report::CheckStatus/DoctorCheckResult (POS: doctor data models)

[OUTPUT]
- check_orphan_processes: doctor check result for orphan automation processes and stale automation sandboxes

[POS]
Adapter between the orphan cleanup primitives and the doctor report model. The
scan walks the psutil process table synchronously, so callers offload it with
asyncio.to_thread.
"""

from __future__ import annotations

from .orphans import find_orphan_automation_processes
from .report import CheckStatus, DoctorCheckResult
from .sandboxes import cleanup_stale_automation_sandboxes


def check_orphan_processes() -> DoctorCheckResult:
    """Check for orphan automation browser processes and stale automation sandboxes."""
    orphans = find_orphan_automation_processes()
    sandbox_stat = cleanup_stale_automation_sandboxes(max_age_hours=24.0, dry_run=True)
    stale_sandboxes = sandbox_stat.get("pruned", 0)
    stale_bytes = sandbox_stat.get("reclaimed_bytes", 0)

    if not orphans and stale_sandboxes == 0:
        return DoctorCheckResult(
            name="orphan_processes",
            status=CheckStatus.OK,
            message="No orphan automation processes or stale sandboxes detected",
            details={
                "count": 0,
                "stale_sandboxes": 0,
                "stale_sandbox_bytes": 0,
            },
        )

    msg_parts: list[str] = []
    if orphans:
        pids_preview: list[int | str] = [o["pid"] for o in orphans[:3]]
        if len(orphans) > 3:
            pids_preview.append("...")
        msg_parts.append(f"{len(orphans)} orphan automation process(es): {pids_preview}")
    if stale_sandboxes > 0:
        reclaimed_mb = round(stale_bytes / (1024 * 1024), 1)
        msg_parts.append(f"{stale_sandboxes} stale sandbox(es) ({reclaimed_mb} MB)")

    return DoctorCheckResult(
        name="orphan_processes",
        status=CheckStatus.WARNING,
        message=f"Found {', '.join(msg_parts)}",
        fix="python -m myrm_agent_harness.toolkits.browser --cleanup-orphans --force",
        details={
            "count": len(orphans),
            "pids": [o["pid"] for o in orphans],
            "paths": [o["user_data_dir"] for o in orphans],
            "stale_sandboxes": stale_sandboxes,
            "stale_sandbox_bytes": stale_bytes,
        },
    )
