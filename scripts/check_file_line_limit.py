#!/usr/bin/env python3
"""File line-count gate for myrm-agent-harness.

Baseline-listed files may exceed ``max_lines`` but must not grow. Unlisted files
must stay at or below ``max_lines``.

Run (from myrm-agent-harness root)::

    uv run python scripts/check_file_line_limit.py
    uv run python scripts/check_file_line_limit.py --baseline scripts/file_line_baseline.txt
    uv run python scripts/check_file_line_limit.py --incremental  # pre-commit: changed files only

Exit codes:
    0  OK
    1  Violations found
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from scripts.boundary_engine import get_changed_harness_files  # noqa: E402

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


def check(
    package_root: Path,
    baseline_path: Path | None,
    max_lines: int,
    files: list[Path] | None = None,
) -> list[str]:
    """Return line-limit violations for the given files (default: all package files).

    ``files`` is the incremental scope used by pre-commit; when None the whole
    package is scanned (CI/full mode). Relative paths are resolved against
    ``package_root.parent`` so baselines stay stable either way.
    """
    errors: list[str] = []
    baseline = _load_baseline(baseline_path) if baseline_path is not None else {}
    src_parent = package_root.parent
    targets = files if files is not None else _iter_py_files(package_root)

    for py_file in targets:
        if not py_file.exists():
            continue
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
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Only check .py files changed in git (for pre-commit hooks)",
    )
    args = parser.parse_args(argv)

    package_root = args.package_root.resolve()
    baseline_path = args.baseline.resolve()
    files: list[Path] | None = None
    if args.incremental:
        changed = get_changed_harness_files(package_root)
        if changed is not None:
            files = sorted(changed)
            if not files:
                print("OK (no harness files changed).")
                return 0
        # git unavailable → fall back to full scan below (files stays None)

    errors = check(package_root, baseline_path, args.max_lines, files=files)
    if errors:
        print("ERROR: File line limit violations:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    scope = f"max {args.max_lines} lines"
    if baseline_path.is_file():
        scope += f" + baseline {baseline_path.name}"
    mode = "incremental" if args.incremental else "full"
    print(f"OK ({scope}, {mode}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
