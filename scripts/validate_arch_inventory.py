#!/usr/bin/env python3
"""Validate module-level _ARCH.md file tables and markdown path references.

Two independent checks:

1. **_ARCH inventory** — module-level ``_ARCH.md`` file tables must list sibling
   ``.py`` files (bidirectional: every py file listed, every listed py on disk).
2. **markdown path refs** (``--md-refs``) — backtick-wrapped relative paths in
   any ``*.md`` under the scanned root must resolve to a real file/directory.
   Resolution rules live in :mod:`scripts.md_ref_validator` (explicit relatives,
   cross-repo aliases, and harness module shortcuts).

Only parses markdown **table rows** (lines starting with ``|``) in ``_ARCH.md`` —
prose mentions of ``other_module.py`` are ignored by check 1; check 2 also scans
prose so that refactor-orphaned paths surface in CI.

Usage:
    python scripts/validate_arch_inventory.py
    python scripts/validate_arch_inventory.py --root src/myrm_agent_harness
    python scripts/validate_arch_inventory.py --root src/myrm_agent_harness/agent
    python scripts/validate_arch_inventory.py --md-refs
    python scripts/validate_arch_inventory.py --json

Exit codes:
    0: All checked directories consistent
    1: Missing/stale _ARCH entries or broken markdown path refs detected
    2: Internal error
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from md_ref_validator import MdRefReport, scan_md_refs

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MONOREPO_ROOT = Path(__file__).resolve().parent.parent.parent
_TABLE_HEADER_CELLS = frozenset({"File", "Module", "Submodule", "文件"})
_PRUNE_DIR_NAMES = frozenset({"__pycache__", "node_modules", ".git", ".venv", ".mypy_cache", ".myrm"})


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


def _is_inventory_file_cell(first: str) -> bool:
    """Return True when the first table cell names a single sibling .py file."""
    if first == "__init__.py":
        return True
    if not first.endswith(".py"):
        return False
    if "/" in first or "\\" in first:
        return False
    # Comparison/prose rows often list multiple paths in one cell.
    if "," in first:
        return False
    stem = first[: -len(".py")]
    return stem.isidentifier()


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
        if _is_inventory_file_cell(first):
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
        if any(part in _PRUNE_DIR_NAMES for part in arch.parts):
            continue
        report = scan_directory(arch.parent)
        if report is not None and report.py_files:
            reports.append(report)
    return reports


def _rel_to_repo(path: Path) -> Path:
    try:
        return path.relative_to(_REPO_ROOT)
    except ValueError:
        return path


def _format_reports(reports: list[DirReport], *, root_label: str) -> str:
    lines = ["=" * 72, f"_ARCH.md inventory validation ({root_label})", "=" * 72]
    failed = False
    for report in reports:
        rel = _rel_to_repo(report.directory)
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
        default=_REPO_ROOT / "src" / "myrm_agent_harness",
        help="Package subtree to scan (default: entire src/myrm_agent_harness/)",
    )
    parser.add_argument(
        "--md-refs",
        action="store_true",
        help="Also validate backtick path references in *.md under the root",
    )
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if not root.is_dir():
        print(f"ERROR: not a directory: {root}", file=sys.stderr)
        return 2

    # The _ARCH.md table inventory reflects this repo's own table convention
    # (harness lists __init__.py; other repos generate tables differently), so
    # table validation only applies inside the harness repo. Cross-repo scans
    # are supported exclusively for markdown path reference validation.
    scan_tables = root.is_relative_to(_REPO_ROOT)
    if not scan_tables and not args.md_refs:
        print(f"ERROR: table inventory validation only supports roots inside {_REPO_ROOT}", file=sys.stderr)
        return 2

    reports = scan_tree(root) if scan_tables else []
    has_fail = any(r.missing_in_arch or r.extra_in_arch for r in reports)

    md_reports: list[MdRefReport] = []
    if args.md_refs:
        md_reports = scan_md_refs(root, _MONOREPO_ROOT, _REPO_ROOT)
        has_fail = has_fail or bool(md_reports)

    if args.json:
        payload = [
            {
                "directory": str(_rel_to_repo(r.directory)),
                "py_files": list(r.py_files),
                "missing_in_arch": list(r.missing_in_arch),
                "extra_in_arch": list(r.extra_in_arch),
            }
            for r in reports
        ]
        if args.md_refs:
            payload.append(
                {
                    "md_refs": [
                        {
                            "md": str(_rel_to_repo(r.md_path)),
                            "broken": [{"ref": ref, "line": line} for ref, line in r.broken_refs],
                        }
                        for r in md_reports
                    ]
                }
            )
        print(json.dumps({"ok": not has_fail, "reports": payload}, indent=2))
    else:
        root_label = _rel_to_repo(root).as_posix()
        if reports:
            print(_format_reports(reports, root_label=root_label))
        if args.md_refs:
            print("=" * 72)
            if md_reports:
                print("FAIL - broken markdown path references")
                for report in md_reports:
                    rel = _rel_to_repo(report.md_path)
                    for ref, line_no in report.broken_refs:
                        print(f"  {rel}:{line_no}: `{ref}` not found")
            else:
                print(f"PASS - markdown path references resolve ({root_label})")

    return 1 if has_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
