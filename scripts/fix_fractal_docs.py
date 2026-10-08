#!/usr/bin/env python3
"""Repair what ``check_fractal_docs.py`` and ``validate_arch_inventory.py`` report.

Fixes (mechanical first drafts built from the docstrings already in the code; refine by hand):

* Python module without ``[INPUT]/[OUTPUT]/[POS]`` -> header added to its module docstring
* ``.py`` file missing from its directory's ``_ARCH.md`` table -> row added (rows of deleted files pruned)
* directory with ``.py`` files but no ``_ARCH.md`` -> ``_ARCH.md`` created and indexed in the parent

Shared worktrees: dry-run is the default and ``--write`` needs explicit PATH arguments, ``--all`` or ``--head``.
Each file is re-read right before it is written and skipped when it changed since the analysis.

``--head`` plans against the committed tree (``git archive HEAD``) and writes only files that are still
byte-identical to HEAD in the worktree (new ``_ARCH.md`` files only where nothing exists yet), so it never touches
other sessions' uncommitted work and its output can be committed as is; ``--commit`` does that, scoped to exactly
the files it wrote. Gaps inside dirty files, and ``_ARCH.md`` rows that would contradict the worktree (a file deleted
there, a file that so far exists only there), are reported and left to their owners.

Usage (from the harness root)::

    python scripts/fix_fractal_docs.py                          # dry-run: what would change
    python scripts/fix_fractal_docs.py --write PATH [PATH ...]  # fix only these files / directories
    python scripts/fix_fractal_docs.py --head --write --commit  # repair gaps already in HEAD, safe in a shared tree
    python scripts/fix_fractal_docs.py --write --all            # fix everything the gates report (own checkout only)

Exit codes:
    0  Nothing left to fix (dry-run: nothing to do; --write: everything applied and the gates are satisfied).
    1  Edits pending (dry-run), or files skipped / changed during the run (--write).
    2  Usage error.

[INPUT]
- scripts/fractal_fix_planner.py: edit planning against both gates and the conflict-checked atomic write
- scripts/check_fractal_docs.py: header baseline loading

[OUTPUT]
- main(): CLI entry point (argument validation, scope, report, exit codes)
- head_plan(): plan against ``git archive HEAD`` and keep only the edits the worktree can take safely
- commit_edits(): commit exactly the files that were written

[POS]
Self-service repair for the fractal-doc gates so a red gate costs one command, not a manual audit.
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_fractal_docs as gate
from fractal_fix_planner import Edit, Plan, apply_plan, build_plan

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PACKAGE_ROOT = _REPO_ROOT / "src" / "myrm_agent_harness"
_BASELINE = _REPO_ROOT / "scripts" / "fractal_header_baseline.txt"
_UNREADABLE = "\0unreadable"
_PATHSPEC_FROM_STDIN = ("--pathspec-from-file=-", "--pathspec-file-nul")
_COMMIT_MESSAGE = """docs(arch): add missing IOP headers, _ARCH.md rows and _ARCH.md files at HEAD

Drafted by scripts/fix_fractal_docs.py --head on a snapshot of HEAD and applied only to files whose worktree
bytes equalled HEAD, so uncommitted work of other sessions is untouched. Descriptions are mechanical drafts
taken from the code's own docstrings.
"""


def _git(repo: Path, *args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(["git", *args], cwd=repo, input=data, capture_output=True, check=True).stdout


def _repo_top(path: Path) -> Path:
    return Path(_git(path, "rev-parse", "--show-toplevel").decode().strip())


def _read(path: Path) -> str | None:
    try:
        return path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError):
        return _UNREADABLE


def _skip_reason(old: str | None, current: str | None) -> str:
    if old is None:
        return "already exists in the worktree"
    return "deleted in the worktree" if current is None else "differs from HEAD in the worktree"


def head_plan(package_root: Path, baseline: frozenset[str]) -> Plan:
    """Plan against the committed tree and keep only the edits the worktree can take without touching other work.

    The analysis runs on ``git archive HEAD``. An edit survives when its target is byte-identical to HEAD in the
    worktree (a new file: absent), which also means the result can be committed without dragging along anybody's
    uncommitted changes. ``_ARCH.md`` rows never contradict the worktree: none is added for a file deleted there and
    none is pruned for a file that so far exists only there.
    """
    top = _repo_top(package_root)
    relative = package_root.relative_to(top)
    archive = _git(top, "archive", "HEAD", "--", relative.as_posix())
    with tempfile.TemporaryDirectory(prefix="fix_fractal_head_") as tmp:
        snapshot = Path(tmp)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(snapshot, filter="data")
        plan = build_plan(
            snapshot / relative,
            baseline,
            lambda _path: True,
            lambda path: (top / path.relative_to(snapshot)).exists(),
        )
        skipped = [(top / path.relative_to(snapshot), reason) for path, reason in plan.skipped]
        edits: list[Edit] = []
        for edit in plan.edits:
            target = top / edit.path.relative_to(snapshot)
            current = _read(target)
            if current == edit.old:
                edits.append(Edit(target, edit.old, edit.new, edit.notes))
            else:
                skipped.append((target, _skip_reason(edit.old, current)))
    return Plan(edits, skipped)


def commit_edits(top: Path, edits: list[Edit]) -> bool:
    """Commit exactly the files in ``edits`` and nothing else; False when another session already committed them."""
    paths = [edit.path.relative_to(top).as_posix() for edit in edits]
    created = [path for edit, path in zip(edits, paths, strict=True) if edit.old is None]
    try:
        if created:
            _git(top, "add", *_PATHSPEC_FROM_STDIN, data="\0".join(created).encode())
        _git(
            top, "commit", "--only", "-q", "-m", _COMMIT_MESSAGE, *_PATHSPEC_FROM_STDIN, data="\0".join(paths).encode()
        )
    except subprocess.CalledProcessError:
        if _git(top, "status", "--porcelain", "--", *paths).strip():
            raise
        return False
    return True


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
        "--head",
        action="store_true",
        help="plan against git HEAD and touch only files identical to HEAD (safe in a shared worktree, no PATH needed)",
    )
    parser.add_argument("--commit", action="store_true", help="with --head --write: commit exactly the files written")
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


def _check_arguments(
    parser: argparse.ArgumentParser, args: argparse.Namespace, package_root: Path, targets: list[Path]
) -> None:
    outside = [path for path in targets if not path.exists() or not path.is_relative_to(package_root)]
    if outside:
        parser.error(f"not inside {package_root}: {', '.join(str(path) for path in outside)}")
    if (args.head or args.all) and targets:
        parser.error("PATH arguments cannot be combined with --head or --all")
    if args.head and args.all:
        parser.error("--head and --all are mutually exclusive")
    if args.commit and not (args.head and args.write):
        parser.error("--commit needs --head --write")
    if args.write and not (targets or args.all or args.head):
        parser.error("--write needs PATH arguments, --head or --all (shared worktrees: touch only your own files)")


def _report(plan: Plan) -> None:
    for edit in plan.edits:
        for note in edit.notes:
            print(f"  {note}")
    for path, reason in plan.skipped:
        print(f"  skip    {path.as_posix()}  {reason}")


def _commit_written(package_root: Path, edits: list[Edit]) -> bool:
    if not edits:
        return True
    try:
        committed = commit_edits(_repo_top(package_root), edits)
    except subprocess.CalledProcessError as exc:
        print(f"  failed  commit  {(exc.stderr or b'').decode().strip()}")
        print("The files above were written but not committed; commit them yourself (git commit --only -- PATH ...).")
        return False
    print(f"Committed {len(edits)} file(s)." if committed else "Already committed by another session.")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    package_root = args.package_root.resolve()
    targets = [path.resolve() for path in args.paths]
    _check_arguments(parser, args, package_root, targets)
    baseline = gate.load_header_baseline(args.header_baseline.resolve()) if args.header_baseline else frozenset()
    in_scope = _scope(targets)

    if args.head:
        try:
            plan = head_plan(package_root, baseline)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            parser.error(f"--head needs git and a checkout with at least one commit ({exc})")
    else:
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
    remaining = Plan([], plan.skipped) if args.head else build_plan(package_root, baseline, in_scope)
    print(f"Wrote {len(plan.edits) - len(failures)} file(s); descriptions are mechanical drafts - refine them by hand.")
    failed = {path for path, _ in failures}
    committed = not args.commit or _commit_written(package_root, [e for e in plan.edits if e.path not in failed])
    if remaining.edits or remaining.skipped:
        print("Still failing the gates:")
        _report(remaining)
    return 1 if failures or remaining.edits or remaining.skipped or not committed else 0


if __name__ == "__main__":
    raise SystemExit(main())
