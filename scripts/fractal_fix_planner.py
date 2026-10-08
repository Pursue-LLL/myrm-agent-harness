"""Edit planning and guarded writing for the fractal-docs fixer.

Combines the gate detectors with the two text engines into whole-file edits. Planning is read-only;
``apply_plan`` re-reads every target right before replacing it, so a file somebody else touched in the meantime is
reported instead of overwritten.

[INPUT]
- scripts/check_fractal_docs.py: detection of missing headers / missing ``_ARCH.md`` and the header-baseline paths
- scripts/validate_arch_inventory.py: detection of missing / stale ``_ARCH.md`` rows
- scripts/fractal_header_engine.py, scripts/fractal_arch_engine.py: text synthesis

[OUTPUT]
- build_plan(): analyse a package root against both gates -> Plan of Edit objects
- apply_plan(): conflict-checked atomic write; returns the edits that could not be written

[POS]
Planning half of scripts/fix_fractal_docs.py, which adds scope handling, the HEAD snapshot mode and scoped commits.
"""

from __future__ import annotations

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
    def __init__(
        self,
        package_root: Path,
        baseline: frozenset[str],
        in_scope: Callable[[Path], bool],
        exists: Callable[[Path], bool],
    ) -> None:
        self.package_root = package_root
        self.baseline = baseline
        self.in_scope = in_scope
        self.exists = exists
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

    def _agrees(self, path: Path, *, present: bool, reason: str) -> bool:
        """Whether ``path`` is (not) in the target tree as a documentation change presumes; else it is reported."""
        if self.exists(path) == present:
            return True
        self.skipped.append((path, reason))
        return False

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
        if not self._agrees(directory, present=True, reason="directory is gone from the worktree"):
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
        wanted = [name for name in report.missing_in_arch if self.in_scope(directory / name)]
        obsolete = list(report.extra_in_arch) if wanted or self.in_scope(directory) else []
        missing = [
            name
            for name in wanted
            if self._agrees(directory / name, present=True, reason="deleted in the worktree; row not added")
        ]
        stale = [
            name
            for name in obsolete
            if self._agrees(directory / name, present=False, reason="exists only in the worktree; row kept")
        ]
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


def build_plan(
    package_root: Path,
    baseline: frozenset[str],
    in_scope: Callable[[Path], bool],
    exists: Callable[[Path], bool] = Path.exists,
) -> Plan:
    """Analyse ``package_root`` against both gates and return the edits that would satisfy them.

    ``exists`` tells whether a path is present in the tree the edits will be applied to. It defaults to the analysed
    tree itself; when planning on a snapshot, it keeps ``_ARCH.md`` rows consistent with the real tree (no row for a
    file deleted there, no pruned row for a file that only exists there).
    """
    return _Planner(package_root, baseline, in_scope, exists).build()


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
