#!/usr/bin/env python3
"""Enforce per-module coverage floors for modules with regression-guard tests.

``fail_under`` in ``pyproject.toml`` is a single project-wide number, so it cannot
express "this guard must stay at 90%". This gate reads an existing coverage data
file (no nested pytest run) and fails when a listed module drops below its floor.

Run (from myrm-agent-harness root)::

    uv run python scripts/check_module_coverage.py --data .coverage

Exit codes:
    0  Every gated module meets its floor
    1  A gated module is below its floor, or the data file is missing
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path

# Modules whose regression guards silently rot when their tests stop running.
# Keep in sync with the tests that guard each module.
COVERAGE_FLOORS: dict[str, float] = {
    "*/myrm_agent_harness/agent/security/guards/context_budget.py": 90.0,
    "*/myrm_agent_harness/agent/_internals/_agent_helpers.py": 90.0,
    "*/myrm_agent_harness/agent/context_management/pipeline/engine.py": 90.0,
    "*/myrm_agent_harness/agent/context_management/pipeline/processors/active_tool_result_prune_processor.py": 90.0,
}


def _file_percent(coverage: object, name: str) -> float:
    """Percentage of statements executed in ``name``; 0.0 when it has no statements."""
    _, statements, _, missing, _ = coverage.analysis2(name)  # type: ignore[attr-defined]
    if not statements:
        return 0.0
    return 100.0 * (len(statements) - len(missing)) / len(statements)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default=".coverage", help="coverage data file to read")
    args = parser.parse_args(argv)

    data_path = Path(args.data)
    if not data_path.is_file():
        print(f"ERROR: coverage data not found: {data_path}", file=sys.stderr)
        print("Run the unit suite with --cov first.", file=sys.stderr)
        return 1

    from coverage import Coverage

    coverage = Coverage(data_file=str(data_path))
    coverage.load()
    measured = {str(Path(name)) for name in coverage.get_data().measured_files()}

    violations: list[tuple[str, float]] = []
    for pattern, floor in COVERAGE_FLOORS.items():
        matches = sorted(name for name in measured if fnmatch.fnmatch(name, pattern))
        if not matches:
            violations.append((f"{pattern} (unmeasured)", 0.0))
            continue
        for name in matches:
            percent = _file_percent(coverage, name)
            if percent < floor:
                violations.append((name, percent))

    if violations:
        print("ERROR: modules below their coverage floor:", file=sys.stderr)
        for name, percent in violations:
            print(f"  - {name}: {percent:.1f}%", file=sys.stderr)
        return 1

    print(f"OK ({len(COVERAGE_FLOORS)} module floor(s) met).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
