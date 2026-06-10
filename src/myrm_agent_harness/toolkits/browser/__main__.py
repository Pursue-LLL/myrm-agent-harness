"""CLI entry point for browser toolkit diagnostics.

Usage:
    python -m myrm_agent_harness.toolkits.browser
    python -m myrm_agent_harness.toolkits.browser --json
    python -m myrm_agent_harness.toolkits.browser --no-launch-test
    python -m myrm_agent_harness.toolkits.browser --check-orphans
    python -m myrm_agent_harness.toolkits.browser --cleanup-orphans --force

[INPUT]
- (none)

[OUTPUT]
- main: Parse execution output from the wrapper script.

[POS]
CLI entry point for browser toolkit diagnostics.
"""

import argparse
import asyncio
import json
import sys

from .doctor import (
    cleanup_orphan_processes,
    find_orphan_automation_processes,
    format_report,
    run_doctor,
)


async def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="browser-doctor",
        description="Diagnose browser automation environment and dependencies",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output report as JSON instead of colored text",
    )
    parser.add_argument(
        "--no-launch-test",
        action="store_true",
        help="Skip browser launch test (faster but less thorough)",
    )
    parser.add_argument(
        "--check-orphans",
        action="store_true",
        help="Check for orphan automation processes (dry-run, no cleanup)",
    )
    parser.add_argument(
        "--cleanup-orphans",
        action="store_true",
        help="Clean up orphan automation processes (requires --force)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force cleanup (required with --cleanup-orphans)",
    )

    args = parser.parse_args()

    if args.check_orphans or args.cleanup_orphans:
        orphans = find_orphan_automation_processes()

        if not orphans:
            print("No orphan automation processes found")
            return 0

        print(f"Found {len(orphans)} orphan automation process(es):")
        for orphan in orphans[:10]:
            print(f" PID {orphan['pid']}: {orphan['name']}")
            print(f" user-data-dir: {orphan['user_data_dir']}")

        if len(orphans) > 10:
            print(f" ... and {len(orphans) - 10} more")

        if args.cleanup_orphans:
            if not args.force:
                print("\n  Dry-run mode (no processes killed)")
                print(" Use --force to actually kill these processes:")
                print(" python -m myrm_agent_harness.toolkits.browser --cleanup-orphans --force")
                return 0

            orphan_pids = [o["pid"] for o in orphans]
            result = cleanup_orphan_processes(orphan_pids, force=True)
            print(f"\n Killed {result['killed']} process(es)")
            if result.get("failed"):
                print(f" Failed to kill {len(result['failed'])} process(es)")

        return 0

    report = await run_doctor(include_launch_test=not args.no_launch_test)

    if args.json:
        output = {
            "summary": report.summary,
            "overall_healthy": report.overall_healthy,
            "checks": {
                name: {
                    "status": check.status.value,
                    "message": check.message,
                    "fix": check.fix,
                    "details": check.details,
                }
                for name, check in report.checks.items()
            },
            "recommendations": report.recommendations,
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print(format_report(report))

    return 0 if report.overall_healthy else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
