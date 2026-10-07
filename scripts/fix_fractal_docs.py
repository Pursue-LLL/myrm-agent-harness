#!/usr/bin/env python3
"""Repair what ``check_fractal_docs.py`` and ``validate_arch_inventory.py`` report.

Fixes (mechanical first drafts built from the docstrings already in the code; refine by hand):

* Python module without ``[INPUT]/[OUTPUT]/[POS]`` -> header added to its module docstring
* ``.py`` file missing from its directory's ``_ARCH.md`` table -> row added (rows of deleted files pruned)
* directory with ``.py`` files but no ``_ARCH.md`` -> ``_ARCH.md`` created and indexed in the parent

Shared worktrees: dry-run is the default and ``--write`` needs explicit PATH arguments (or ``--all``), so a
session only touches its own files. Each file is re-read right before it is written and skipped when it
changed since the analysis.

Usage (from the harness root)::

    python scripts/fix_fractal_docs.py                          # dry-run: what would change
    python scripts/fix_fractal_docs.py --write PATH [PATH ...]  # fix only these files / directories
    python scripts/fix_fractal_docs.py --write --all            # fix everything the gates report

Exit codes:
    0  Nothing left to fix (dry-run: nothing to do; --write: everything applied and the gates are satisfied).
    1  Edits pending (dry-run), or files skipped / changed during the run (--write).
    2  Usage error.

[INPUT]
- scripts/check_fractal_docs.py: gate detection (missing headers, missing ``_ARCH.md``) and header baseline
- scripts/validate_arch_inventory.py: gate detection of missing / stale ``_ARCH.md`` rows
- scripts/fractal_header_engine.py, scripts/fractal_arch_engine.py: text synthesis

[OUTPUT]
- main(): CLI entry point; build_plan() / apply_plan(): analysis and guarded write phases

[POS]
Self-service repair for the fractal-doc gates so a red gate costs one command, not a manual audit.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_fractal_docs as gate
import validate_arch_inventory as inventory
from fractal_arch_engine import add_subpackage_row, overview_of, render_new_arch, update_file_table
from fractal_header_engine import HeaderError, add_header, module_summary

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PACKAGE_ROOT = _REPO_ROOT / "src" / "myrm_agent_harness"
_BASELINE = _REPO_ROOT / "scripts" / "fractal_header_baseline.txt"


@dataclass
class Edit:
    path: Path
    old: str | None  # None: the file must not exist yet
    new: str
    notes: list[str] = field(default_factory=list)


@dataclass
class Plan:
    edits: list[Edit]
    skipped: list[tuple[Path, str]]


class ConflictError(Exception):
    """The file changed between analysis and write."""


class _Planner:
    def __init__(self, package_root: Path, baseline: frozenset[str], in_scope: Callable[[Path], bool]) -> None:
        self.package_root = package_root
        self.baseline = baseline
        self.in_scope = in_scope
        self.edits: dict[Path, Edit] = {}
        self.skipped: list[tuple[Path, str]] = []
        self.summaries: dict[Path, str] = {}

    def build(self) -> Plan:
        self._plan_headers()
        self._plan_arch()
        return Plan(list(self.edits.values()), self.skipped)

    # ------------------------------------------------------------------ helpers

    def _rel(self, path: Path) -> str:
        try:
            return path.relative_to(self.package_root.parent.parent).as_posix()
        except ValueError:
            return path.as_posix()

    def _load(self, path: Path) -> str | None:
        try:
            text = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self.skipped.append((path, f"unreadable: {exc}"))
            return None
        if "\r" in text:
            self.skipped.append((path, "CR/CRLF line endings are not supported"))
            return None
        return text

    def _current(self, path: Path) -> str | None:
        edit = self.edits.get(path)
        if edit is not None:
            return edit.new
        return self._load(path) if path.is_file() else None

    def _stage(self, path: Path, new: str, note: str) -> None:
        edit = self.edits.get(path)
        if edit is not None:
            edit.new = new
            edit.notes.append(note)
            return
        old = self._load(path) if path.is_file() else None
        if old is None and path.is_file():
            return
        self.edits[path] = Edit(path, old, new, [note])

    def _summary(self, path: Path) -> str:
        return self.summaries.get(path) or module_summary(path)

    # ------------------------------------------------------------------ headers

    def _plan_headers(self) -> None:
        for path in gate.missing_io_headers(self.package_root):
            if gate.rel_package_path(self.package_root, path) in self.baseline or not self.in_scope(path):
                continue
            source = self._load(path)
            if source is None:
                continue
            try:
                result = add_header(source, path, self.package_root)
            except HeaderError as exc:
                self.skipped.append((path, str(exc)))
                continue
            self.summaries[path] = result.summary
            self.edits[path] = Edit(path, source, result.source, [f"header  {self._rel(path)}  {result.summary}"])

    # -------------------------------------------------------------------- _ARCH

    def _plan_arch(self) -> None:
        missing = set(gate.missing_arch_dirs(self.package_root))
        reports = {report.directory: report for report in inventory.scan_tree(self.package_root)}
        for directory in sorted(missing | set(reports), key=lambda d: (len(d.parts), d.as_posix())):
            if directory in missing:
                self._create_arch(directory)
            else:
                self._update_arch(directory, reports[directory])

    def _create_arch(self, directory: Path) -> None:
        names = sorted(p.name for p in directory.iterdir() if p.is_file() and p.suffix == ".py")
        if not any(self.in_scope(directory / name) for name in names):
            return
        rows = {name: self._summary(directory / name) for name in names}
        overview = overview_of(rows)
        arch = directory / "_ARCH.md"
        self._stage(
            arch, render_new_arch(directory.name, overview, rows), f"create  {self._rel(arch)}  ({len(rows)} files)"
        )
        if directory == self.package_root:
            return
        parent = directory.parent / "_ARCH.md"
        parent_text = self._current(parent)
        updated = add_subpackage_row(parent_text, directory.name, overview) if parent_text is not None else None
        if updated is not None:
            self._stage(parent, updated, f"index   {self._rel(parent)}  + {directory.name}/")

    def _update_arch(self, directory: Path, report: inventory.DirReport) -> None:
        missing = [name for name in report.missing_in_arch if self.in_scope(directory / name)]
        stale = list(report.extra_in_arch) if missing or self.in_scope(directory) else []
        if not missing and not stale:
            return
        arch = directory / "_ARCH.md"
        text = self._current(arch)
        if text is None:
            return
        add = {name: self._summary(directory / name) for name in missing}
        new = update_file_table(text, add, stale)
        if new != text:
            changes = ", ".join([*(f"+{name}" for name in missing), *(f"-{name}" for name in stale)])
            self._stage(arch, new, f"table   {self._rel(arch)}  {changes}")


def build_plan(package_root: Path, baseline: frozenset[str], in_scope: Callable[[Path], bool]) -> Plan:
    """Analyse ``package_root`` against both gates and return the edits that would satisfy them."""
    return _Planner(package_root, baseline, in_scope).build()


def _write(edit: Edit) -> None:
    path = edit.path
    if edit.old is None:
        if path.exists():
            raise ConflictError("created by someone else during the run")
    elif path.read_bytes().decode("utf-8") != edit.old:
        raise ConflictError("changed on disk during the run; re-run to pick up the new content")
    temp = path.with_name(f".{path.name}.fixtmp")
    temp.write_text(edit.new, encoding="utf-8")
    if path.exists():
        shutil.copymode(path, temp)
    os.replace(temp, path)


def apply_plan(plan: Plan) -> list[tuple[Path, str]]:
    """Write every edit atomically; returns the ``(path, reason)`` of those that could not be written."""
    failures: list[tuple[Path, str]] = []
    for edit in plan.edits:
        try:
            _write(edit)
        except (ConflictError, OSError, ValueError) as exc:
            failures.append((edit.path, str(exc)))
    return failures


def _scope(targets: list[Path]) -> Callable[[Path], bool]:
    if not targets:
        return lambda _path: True
    return lambda path: any(path == target or target in path.parents for target in targets)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.split("[INPUT]")[0], formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "paths", nargs="*", type=Path, help="files or directories to fix (default scope: whole package)"
    )
    parser.add_argument("--write", action="store_true", help="apply the edits (default: dry-run)")
    parser.add_argument("--all", action="store_true", help="with --write: fix everything the gates report")
    parser.add_argument(
        "--package-root", type=Path, default=_PACKAGE_ROOT, help="harness package (default: src/myrm_agent_harness)"
    )
    parser.add_argument(
        "--header-baseline",
        type=Path,
        default=_BASELINE if _BASELINE.is_file() else None,
        help="legacy paths allowed to lack a header, as used by the CI gate",
    )
    return parser


def _report(plan: Plan) -> None:
    for edit in plan.edits:
        for note in edit.notes:
            print(f"  {note}")
    for path, reason in plan.skipped:
        print(f"  skip    {path.as_posix()}  {reason}")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    package_root = args.package_root.resolve()
    targets = [path.resolve() for path in args.paths]
    outside = [path for path in targets if not path.exists() or not path.is_relative_to(package_root)]
    if outside:
        parser.error(f"not inside {package_root}: {', '.join(str(path) for path in outside)}")
    if args.write and not targets and not args.all:
        parser.error("--write needs explicit PATH arguments or --all (shared worktrees: touch only your own files)")
    if args.all and targets:
        parser.error("--all cannot be combined with PATH arguments")
    baseline = gate.load_header_baseline(args.header_baseline.resolve()) if args.header_baseline else frozenset()
    in_scope = _scope(targets)

    plan = build_plan(package_root, baseline, in_scope)
    _report(plan)
    if not plan.edits and not plan.skipped:
        print("Nothing to fix.")
        return 0
    if not args.write:
        print(f"Dry run: {len(plan.edits)} file(s) would change, {len(plan.skipped)} skipped. Re-run with --write.")
        return 1

    failures = apply_plan(plan)
    for path, reason in failures:
        print(f"  failed  {path.as_posix()}  {reason}")
    remaining = build_plan(package_root, baseline, in_scope)
    print(f"Wrote {len(plan.edits) - len(failures)} file(s); descriptions are mechanical drafts - refine them by hand.")
    if remaining.edits or remaining.skipped:
        print("Still failing the gates:")
        _report(remaining)
    return 1 if failures or remaining.edits or remaining.skipped else 0


if __name__ == "__main__":
    raise SystemExit(main())
