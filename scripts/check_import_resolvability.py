#!/usr/bin/env python3
"""Import-resolvability gate: every first-party import must resolve to a real module and name.

A function-local ``from pkg.mod import name`` wrapped in ``try / except Exception`` fails only
when its path runs, and the failure is swallowed into a log line or a fabricated fallback, so a
module move or rename silently kills the feature behind it. This gate resolves every import of
the scanned packages statically: the module must exist and the imported name must be a submodule
or be bound at import time. There is no allowlist and no baseline: fix the import or delete the
dead path.

Usage:
    python scripts/check_import_resolvability.py                  # Harness full scan (CI mode)
    python scripts/check_import_resolvability.py --incremental    # Pre-commit: skip unless harness sources changed
    python scripts/check_import_resolvability.py --json           # Machine-readable output
    python scripts/check_import_resolvability.py \\
        --package app=../myrm-agent/myrm-agent-server/app \\
        --package myrm_agent_harness=src/myrm_agent_harness --scan app    # Server tree against the harness

Exit codes:
    0: Every first-party import resolves (or the check was skipped, loudly)
    1: One or more unresolved imports
    2: Nothing was scanned, a file could not be parsed, or the arguments are invalid
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from scripts.import_resolvability_engine import Report, analyze  # noqa: E402
from scripts.tool_registry_config import HARNESS_SRC  # noqa: E402

_PACKAGE = "myrm_agent_harness"
_SOURCE_PREFIX = "src/myrm_agent_harness/"


def parse_packages(values: Sequence[str]) -> dict[str, Path]:
    """Parse repeated ``NAME=DIR`` arguments into ``{package name: directory}``."""
    packages: dict[str, Path] = {}
    for value in values:
        name, separator, directory = value.partition("=")
        path = Path(directory).resolve()
        if not separator or not name.isidentifier() or not path.is_dir():
            raise ValueError(f"--package expects NAME=DIR with an existing directory, got {value!r}")
        packages[name] = path
    return packages


def _git_paths(*args: str) -> set[str] | None:
    try:
        result = subprocess.run(["git", *args], capture_output=True, text=True, timeout=10, cwd=_REPO_ROOT, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def harness_sources_changed() -> bool:
    """True when staged/unstaged changes touch harness Python sources (or git is unavailable).

    Deletions count: removing a module breaks importers that were not themselves edited.
    """
    staged = _git_paths("diff", "--cached", "--name-only")
    unstaged = _git_paths("diff", "--name-only")
    if staged is None or unstaged is None:
        return True
    return any(path.startswith(_SOURCE_PREFIX) and path.endswith(".py") for path in staged | unstaged)


def _display(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _print_report(report: Report, elapsed: float) -> None:
    print(
        f"import resolvability: {report.files_scanned} files, "
        f"{report.imports_checked} first-party imports checked ({elapsed:.1f}s CPU)."
    )
    for path in report.unparsable:
        print(f"WARNING: could not parse {_display(path)}; its imports were not checked.", file=sys.stderr)
    if not report.findings:
        if not report.unparsable:
            print("OK: every first-party import resolves.")
        return
    print(f"FAIL: {len(report.findings)} unresolved import(s):", file=sys.stderr)
    for finding in report.findings:
        print(f"  {_display(finding.path)}:{finding.line}: {finding.target} ({finding.reason})", file=sys.stderr)
    print(
        "Point each import at the symbol's real location, or delete the dead path behind it. "
        "A try/except around the import does not make it resolvable and there is no allowlist.",
        file=sys.stderr,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Every first-party import must resolve.")
    parser.add_argument(
        "--package",
        action="append",
        default=[],
        metavar="NAME=DIR",
        help="Top-level package and its directory (repeatable; default: the harness)",
    )
    parser.add_argument(
        "--scan",
        action="append",
        default=[],
        metavar="NAME",
        help="Package whose imports are checked (repeatable; default: every --package)",
    )
    parser.add_argument("--incremental", action="store_true", help="Harness mode: skip unless harness sources changed")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args(argv)

    try:
        packages = parse_packages(args.package) or {_PACKAGE: HARNESS_SRC}
    except ValueError as error:
        parser.error(str(error))
    scan = args.scan or list(packages)
    unknown = sorted(set(scan) - set(packages))
    if unknown:
        parser.error(f"--scan names not given as --package: {', '.join(unknown)}")

    if args.incremental and not args.package and not harness_sources_changed():
        print("import resolvability: skipped (no harness source change).")
        return 0

    started = time.process_time()
    report = analyze(packages, scan)
    elapsed = time.process_time() - started
    if report.files_scanned == 0:
        print("ERROR: no Python files found, nothing was scanned.", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "files": report.files_scanned,
                    "imports": report.imports_checked,
                    "findings": [
                        {"path": _display(f.path), "line": f.line, "target": f.target, "reason": f.reason}
                        for f in report.findings
                    ],
                    "unparsable": [_display(path) for path in report.unparsable],
                },
                indent=2,
            )
        )
    else:
        _print_report(report, elapsed)
    if report.findings:
        return 1
    return 2 if report.unparsable else 0


if __name__ == "__main__":
    raise SystemExit(main())
