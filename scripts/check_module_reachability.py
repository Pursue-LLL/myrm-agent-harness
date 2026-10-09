#!/usr/bin/env python3
"""Module-reachability gate: engine units must have a production consumer.

Every direct child (file or sub-package) of an engine directory under ``agent/``,
``runtime/`` and ``core/`` must be used by production code, in this package or in the
server tree. A unit that exists, passes its own tests and is re-exported from an
``__init__.py`` but is called by nothing is a dead feature path and fails the gate.
There is no allowlist: wire the unit into a production call site (covered by a test
that drives the real entry point) or delete it. ``toolkits/`` is the optional tool
library and is out of scope.

Usage:
    python scripts/check_module_reachability.py                  # Full scan (CI mode)
    python scripts/check_module_reachability.py --incremental    # Pre-commit mode
    python scripts/check_module_reachability.py --require-server # Fail when the server tree is absent
    python scripts/check_module_reachability.py --json           # Machine-readable output

Exit codes:
    0: Every unit is reachable (or the check was skipped / not evaluable, loudly)
    1: One or more unreachable units
    2: Internal error (nothing was scanned)
    3: Server tree missing while --require-server is set
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from scripts.module_reachability_engine import Report, Unit, analyze  # noqa: E402
from scripts.tool_registry_config import HARNESS_SRC, SERVER_SRC  # noqa: E402

_SOURCE_PREFIX = "src/myrm_agent_harness/"


def project_entry_points(pyproject: Path) -> tuple[str, ...]:
    """``module:attr`` targets of ``[project.scripts]`` (installed console scripts are roots)."""
    if not pyproject.is_file():
        return ()
    scripts = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {}).get("scripts", {})
    return tuple(str(target) for target in scripts.values())


def _git_paths(*args: str) -> set[str] | None:
    try:
        result = subprocess.run(["git", *args], capture_output=True, text=True, timeout=10, cwd=_REPO_ROOT, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def harness_sources_changed() -> bool:
    """True when staged/unstaged changes touch harness Python sources (or git is unavailable)."""
    staged = _git_paths("diff", "--cached", "--name-only")
    unstaged = _git_paths("diff", "--name-only")
    if staged is None or unstaged is None:
        return True
    return any(
        (path.startswith(_SOURCE_PREFIX) and path.endswith(".py")) or path == "pyproject.toml"
        for path in staged | unstaged
    )


def _format_units(units: tuple[Unit, ...]) -> list[str]:
    return [f"  {unit.key}  ({unit.lines} lines)" for unit in units]


def _print_report(report: Report, elapsed: float, *, verbose: bool) -> None:
    print(
        f"module reachability: {len(report.units)} units in {report.files_scanned} files, "
        f"{len(report.server_only)} reachable only through the server tree ({elapsed:.1f}s CPU)."
    )
    if verbose and report.server_only:
        print("Server-only units:")
        print("\n".join(_format_units(report.server_only)))
    if not report.dead:
        print("OK: every unit has a production consumer.")
        return
    print(f"FAIL: {len(report.dead)} unit(s) have no production consumer:", file=sys.stderr)
    print("\n".join(_format_units(report.dead)), file=sys.stderr)
    print(
        "Wire each unit into a production call site covered by a test that drives the real entry point, "
        "or delete it. A re-export in an __init__.py is not a consumer and there is no allowlist.",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Engine units must have a production consumer.")
    parser.add_argument("--incremental", action="store_true", help="Skip unless harness sources changed in git")
    parser.add_argument("--require-server", action="store_true", help="Fail when the server tree is absent")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    parser.add_argument("--verbose", action="store_true", help="Also list server-only units")
    args = parser.parse_args(argv)

    if args.incremental and not harness_sources_changed():
        print("module reachability: skipped (no harness source change).")
        return 0
    if not SERVER_SRC.is_dir():
        if args.require_server:
            print(f"ERROR: server tree not found at {SERVER_SRC}", file=sys.stderr)
            return 3
        print(
            f"module reachability: NOT EVALUATED - server tree not found at {SERVER_SRC}; "
            "units consumed only by the server cannot be told apart from dead ones in a standalone checkout."
        )
        return 0

    started = time.process_time()
    report = analyze(HARNESS_SRC, [SERVER_SRC], project_entry_points(_REPO_ROOT / "pyproject.toml"))
    elapsed = time.process_time() - started
    if not report.units:
        print("ERROR: no engine units found, nothing was scanned.", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "units": len(report.units),
                    "dead": [{"unit": unit.key, "lines": unit.lines} for unit in report.dead],
                    "server_only": [{"unit": unit.key, "lines": unit.lines} for unit in report.server_only],
                },
                indent=2,
            )
        )
    else:
        _print_report(report, elapsed, verbose=args.verbose)
    return 1 if report.dead else 0


if __name__ == "__main__":
    raise SystemExit(main())
