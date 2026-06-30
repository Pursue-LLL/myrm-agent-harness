#!/usr/bin/env python3
"""Validate that module-level _ARCH.md file tables list sibling .py files.

Only parses markdown **table rows** (lines starting with ``|``) in ``_ARCH.md`` —
prose mentions of ``other_module.py`` are ignored.

Usage:
    python scripts/validate_arch_inventory.py
    python scripts/validate_arch_inventory.py --root src/myrm_agent_harness/agent/middlewares
    python scripts/validate_arch_inventory.py --json

Exit codes:
    0: All checked directories consistent
    1: Missing or stale _ARCH entries detected
    2: Internal error
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_AGENT_ROOT = _REPO_ROOT / "src" / "myrm_agent_harness" / "agent"
_TABLE_HEADER_CELLS = frozenset({"File", "Module", "Submodule", "文件"})


@dataclass(frozen=True)
class DirReport:
    directory: Path
    py_files: tuple[str, ...]
    arch_path: Path
    listed: frozenset[str]
    missing_in_arch: tuple[str, ...]
    extra_in_arch: tuple[str, ...]


def _collect_py_files(directory: Path) -> list[str]:
    return sorted(
        p.name
        for p in directory.iterdir()
        if p.is_file() and p.suffix == ".py"
    )


def _first_table_cell(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    cells = [cell.strip() for cell in stripped.split("|")]
    if len(cells) < 3:
        return None
    return cells[1].strip("`").strip()


def _listed_py_in_arch(arch_path: Path) -> set[str]:
    listed: set[str] = set()
    for line in arch_path.read_text(encoding="utf-8").splitlines():
        first = _first_table_cell(line)
        if first is None:
            continue
        if first in _TABLE_HEADER_CELLS:
            continue
        if first.startswith("---") or first.startswith("—"):
            continue
        if first.endswith(".py"):
            listed.add(first)
    return listed


def scan_directory(directory: Path) -> DirReport | None:
    arch_path = directory / "_ARCH.md"
    if not arch_path.is_file():
        return None
    py_files = _collect_py_files(directory)
    listed = _listed_py_in_arch(arch_path)
    py_set = set(py_files)
    missing = tuple(sorted(py_set - listed))
    extra = tuple(sorted(listed - py_set))
    return DirReport(
        directory=directory,
        py_files=tuple(py_files),
        arch_path=arch_path,
        listed=frozenset(listed),
        missing_in_arch=missing,
        extra_in_arch=extra,
    )


def scan_tree(root: Path) -> list[DirReport]:
    reports: list[DirReport] = []
    for arch in sorted(root.rglob("_ARCH.md")):
        report = scan_directory(arch.parent)
        if report is not None and report.py_files:
            reports.append(report)
    return reports


def _format_reports(reports: list[DirReport]) -> str:
    lines = ["=" * 72, "_ARCH.md inventory validation (agent/)", "=" * 72]
    failed = False
    for report in reports:
        rel = report.directory.relative_to(_REPO_ROOT)
        if report.missing_in_arch or report.extra_in_arch:
            failed = True
            lines.append(f"\nFAIL {rel}")
            if report.missing_in_arch:
                lines.append(f"  missing in _ARCH: {', '.join(report.missing_in_arch)}")
            if report.extra_in_arch:
                lines.append(f"  listed but not on disk: {', '.join(report.extra_in_arch)}")
        else:
            lines.append(f"OK   {rel} ({len(report.py_files)} py files)")
    lines.append("")
    lines.append("PASS" if not failed else "FAIL - fix _ARCH.md file tables")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate _ARCH.md py file inventories")
    parser.add_argument(
        "--root",
        type=Path,
        default=_AGENT_ROOT,
        help="Subdirectory under agent/ to scan (default: entire agent/)",
    )
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if not root.is_dir():
        print(f"ERROR: not a directory: {root}", file=sys.stderr)
        return 2

    reports = scan_tree(root)
    has_fail = any(r.missing_in_arch or r.extra_in_arch for r in reports)

    if args.json:
        payload = [
            {
                "directory": str(r.directory.relative_to(_REPO_ROOT)),
                "py_files": list(r.py_files),
                "missing_in_arch": list(r.missing_in_arch),
                "extra_in_arch": list(r.extra_in_arch),
            }
            for r in reports
        ]
        print(json.dumps({"ok": not has_fail, "reports": payload}, indent=2))
    else:
        print(_format_reports(reports))

    return 1 if has_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
