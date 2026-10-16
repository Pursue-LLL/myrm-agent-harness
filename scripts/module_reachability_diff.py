"""Diff mode of the module-reachability gate: a change may not leave a unit without a production consumer.

The absolute gate fails while any unit is unwired, which in-flight work keeps true for long stretches.
Diff mode stays enforceable regardless: a unit fails only when it is dead now and was not dead at the
merge-base with a reference revision, so it names exactly the units a change orphans or adds unwired.
"Now" is the working tree as it lies on disk, untracked files included: the verdict covers committed
changes only on a clean checkout, which is what CI runs.

There is no baseline file and no allowlist. The comparison tree is rebuilt from git on every run, so a
unit is "already dead" only because it really was dead at the merge-base. Whatever cannot be established
(not a git tree, unknown revision, no common ancestor, package missing at the base) raises
``BaseUnavailableError``; callers must fail closed instead of passing silently.
"""

from __future__ import annotations

import io
import subprocess
import tarfile
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from scripts.module_reachability_engine import Report, Unit

_GIT_TIMEOUT_SECONDS = 120

# Builds the report of one tree: ``(package_root, repository_root)``. The repository root is where files
# that sit next to the package in that revision (``pyproject.toml``) can be read.
Analyse = Callable[[Path, Path], Report]


class BaseUnavailableError(RuntimeError):
    """The comparison revision could not be established; the gate must fail closed."""


@dataclass(frozen=True)
class DiffResult:
    base: str
    introduced: tuple[Unit, ...]
    preexisting: int


def _git(repo: Path, *args: str) -> bytes:
    try:
        done = subprocess.run(["git", *args], cwd=repo, capture_output=True, timeout=_GIT_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise BaseUnavailableError(f"git {args[0]} could not run: {exc}") from exc
    if done.returncode != 0:
        raise BaseUnavailableError(f"git {args[0]} failed: {done.stderr.decode(errors='replace').strip()}")
    return done.stdout


def _repository_root(path: Path) -> Path:
    return Path(_git(path, "rev-parse", "--show-toplevel").decode().strip())


def _merge_base(repo: Path, rev: str) -> str:
    if rev.startswith("-"):
        raise BaseUnavailableError(f"not a revision: {rev!r}")
    return _git(repo, "merge-base", "HEAD", rev).decode().strip()


def _extract(repo: Path, rev: str, paths: Sequence[str], destination: Path) -> None:
    archive = _git(repo, "archive", "--format=tar", rev, "--", *paths)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(destination, filter="data")


def introduced_dead(head: Report, base: Report) -> tuple[Unit, ...]:
    """Units dead in ``head`` that were not dead in ``base`` (new, or left without a consumer)."""
    already_dead = {unit.key for unit in base.dead}
    return tuple(unit for unit in head.dead if unit.key not in already_dead)


def diff_against(
    head: Report,
    package_root: Path,
    rev: str,
    analyse: Analyse,
    *,
    sibling_files: Sequence[str] = (),
) -> DiffResult:
    """Compare ``head`` with the same package at the merge-base of ``HEAD`` and ``rev``.

    ``sibling_files`` are repository-root files the analysis reads next to the package; they are
    taken from the base revision as well, so base and head are analysed under the same rules.
    """
    package_root = package_root.resolve()
    repo = _repository_root(package_root)
    relative = package_root.relative_to(repo).as_posix()
    base = _merge_base(repo, rev)
    with tempfile.TemporaryDirectory(prefix="reachability-base-") as scratch:
        scratch_root = Path(scratch)
        _extract(repo, base, [relative, *sibling_files], scratch_root)
        base_report = analyse(scratch_root / relative, scratch_root)
    if not base_report.units:
        raise BaseUnavailableError(f"no engine units found in {relative} at {base[:10]}")
    introduced = introduced_dead(head, base_report)
    return DiffResult(base=base, introduced=introduced, preexisting=len(head.dead) - len(introduced))
