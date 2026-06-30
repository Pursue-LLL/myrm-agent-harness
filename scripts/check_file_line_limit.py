#!/usr/bin/env python3
"""File line-count gate for myrm-agent-harness.

Baseline-listed files may exceed ``max_lines`` but must not grow. Unlisted files
must stay at or below ``max_lines``.

Run (from myrm-agent-harness root)::

    uv run python scripts/check_file_line_limit.py
    uv run python scripts/check_file_line_limit.py --baseline scripts/file_line_baseline.txt

Exit codes:
    0  OK
    1  Violations found
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_DEFAULT_MAX_LINES = 500
_PRUNE = frozenset({"__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"})


def _count_lines(path: Path) -> int:
    return sum(1 for _ in path.open("rb"))


def _load_baseline(path: Path) -> dict[str, int]:
    baseline: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "\t" in stripped:
            rel, count_str = stripped.split("\t", 1)
            baseline[rel.strip()] = int(count_str.strip())
        else:
            baseline[stripped] = _DEFAULT_MAX_LINES + 1
    return baseline


def _iter_py_files(package_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(package_root.rglob("*.py")):
        if any(part in _PRUNE for part in path.parts):
            continue
        files.append(path)
    return files


def check(package_root: Path, baseline_path: Path | None, max_lines: int) -> list[str]:
    errors: list[str] = []
    baseline = _load_baseline(baseline_path) if baseline_path is not None else {}
    src_parent = package_root.parent

    for py_file in _iter_py_files(package_root):
        rel = str(py_file.relative_to(src_parent))
        line_count = _count_lines(py_file)
        if rel in baseline:
            allowed = baseline[rel]
            if line_count > allowed:
                errors.append(
                    f"{rel}: {line_count} lines exceeds baseline cap {allowed} "
                    f"(+{line_count - allowed}); split file or shrink before merging"
                )
            continue
        if line_count > max_lines:
            errors.append(
                f"{rel}: {line_count} lines exceeds max {max_lines} "
                f"(not in baseline — add only after intentional split plan)"
            )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_root = Path(__file__).resolve().parent.parent / "src" / "myrm_agent_harness"
    default_baseline = Path(__file__).resolve().parent / "file_line_baseline.txt"
    parser.add_argument("--package-root", type=Path, default=default_root)
    parser.add_argument("--baseline", type=Path, default=default_baseline)
    parser.add_argument("--max-lines", type=int, default=_DEFAULT_MAX_LINES)
    args = parser.parse_args(argv)

    errors = check(args.package_root.resolve(), args.baseline.resolve(), args.max_lines)
    if errors:
        print("ERROR: File line limit violations:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    scope = f"max {args.max_lines} lines"
    if args.baseline.is_file():
        scope += f" + baseline {args.baseline.name}"
    print(f"OK ({scope}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
