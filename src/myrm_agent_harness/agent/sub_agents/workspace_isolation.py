"""Workspace isolation for subagent execution.

Provides ISOLATED_COPY workspace policy: clone the parent workspace with
:func:`shutil.copytree` (uses OS copy-on-write when the platform supports it)
for true isolation. After the child finishes, :func:`_sync_tree` mirrors
changes back to the parent, avoiding fragile git diff/apply on untracked
or binary files.

[INPUT]
- (none)

[OUTPUT]
- isolated_workspace: Context manager that creates an isolated workspace copy.
- WorkspaceCloneTooLargeError: Raised when workspace exceeds max_bytes.

[POS]
Workspace isolation for subagent execution.
"""

from __future__ import annotations

import asyncio
import filecmp
import logging
import os
import shutil
import tempfile
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

_CLONE_IGNORE_DIRS: frozenset[str] = frozenset({
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    "dist",
    "build",
    ".next",
})

_DEFAULT_MAX_CLONE_BYTES: int = 1024 * 1024 * 1024  # 1 GiB


class WorkspaceCloneTooLargeError(RuntimeError):
    """Raised when the source workspace exceeds the max clone size."""


def _estimate_clone_size(src: Path, ignore_dirs: frozenset[str]) -> int:
    """Estimate the byte size of ``src`` excluding ignored directories."""
    total = 0
    for dirpath, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def _clone_workspace(
    src: Path,
    dst: Path,
    *,
    max_bytes: int = _DEFAULT_MAX_CLONE_BYTES,
) -> int:
    """Recursively clone src into dst. Returns count of files copied.

    Uses shutil.copytree which automatically utilizes OS-level Copy-on-Write
    (like APFS clonefile on macOS or Btrfs reflinks on Linux) when available.
    This provides true isolation (unlike hardlinks which leak in-place edits)
    while maintaining near-instant creation speed on modern filesystems.

    Skips heavyweight non-source directories (node_modules, .git, dist, etc.)
    that subagents never need to modify, dramatically reducing clone time on
    filesystems without COW support (e.g. Docker overlay2).

    Raises :class:`WorkspaceCloneTooLargeError` if the filtered source
    exceeds ``max_bytes`` (default 1 GiB).
    """
    estimated = _estimate_clone_size(src, _CLONE_IGNORE_DIRS)
    if estimated > max_bytes:
        raise WorkspaceCloneTooLargeError(
            f"Workspace {src} is ~{estimated / (1024 * 1024):.0f} MiB "
            f"(limit {max_bytes / (1024 * 1024):.0f} MiB). "
            f"Cannot create isolated copy."
        )

    file_count = 0

    def _counting_copy2(src_file: str, dst_file: str) -> str:
        nonlocal file_count
        file_count += 1
        return shutil.copy2(src_file, dst_file)

    shutil.copytree(
        src,
        dst,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(*_CLONE_IGNORE_DIRS),
        copy_function=_counting_copy2,
    )
    return file_count


def _merge_tree_additive(src: Path, dst: Path) -> None:
    """Merge src into dst without deleting files that exist only in dst.

    Used when multiple isolated subagents merge back into the same parent workspace.
    """
    ignore_dirs = {".git"}
    for src_dir, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        rel_path = os.path.relpath(src_dir, src)
        dst_dir = dst / rel_path if rel_path != "." else dst
        dst_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            src_file = Path(src_dir) / f
            dst_file = dst_dir / f
            if not dst_file.exists() or not filecmp.cmp(src_file, dst_file, shallow=True):
                shutil.copy2(src_file, dst_file)


def _sync_tree(src: Path, dst: Path) -> None:
    """Perfectly mirror src directory to dst directory.

    Handles additions, modifications, and deletions.
    Optimized with shallow=True (stat-based compare) for performance.
    Safeguards critical metadata directories (like .git) from being overwritten.
    """
    # Critical safeguards: Do not sync version control metadata from a speculative branch
    # back to the main workspace, as it will corrupt the main repository's state.
    ignore_dirs = {".git"}

    # 1. Traverse src and copy/overwrite to dst (Additions & Modifications)
    for src_dir, dirs, files in os.walk(src):
        # Filter ignored directories in-place so os.walk skips them
        dirs[:] = [d for d in dirs if d not in ignore_dirs]

        rel_path = os.path.relpath(src_dir, src)
        dst_dir = dst / rel_path if rel_path != "." else dst

        if not dst_dir.exists():
            dst_dir.mkdir(parents=True, exist_ok=True)

        for f in files:
            src_file = Path(src_dir) / f
            dst_file = dst_dir / f
            # Copy if destination doesn't exist, or if stat signatures differ (shallow=True)
            if not dst_file.exists() or not filecmp.cmp(src_file, dst_file, shallow=True):
                shutil.copy2(src_file, dst_file)

    # 2. Traverse dst and delete things not in src (Deletions)
    for dst_dir, dirs, files in os.walk(dst, topdown=False):
        # Filter ignored directories in-place so we don't delete them from dst!
        dirs[:] = [d for d in dirs if d not in ignore_dirs]

        rel_path = os.path.relpath(dst_dir, dst)
        src_dir = src / rel_path if rel_path != "." else src

        for f in files:
            src_file = src_dir / f
            if not src_file.exists():
                (Path(dst_dir) / f).unlink(missing_ok=True)

        for d in dirs:
            src_d = src_dir / d
            if not src_d.exists():
                shutil.rmtree(Path(dst_dir) / d, ignore_errors=True)


async def _sync_workspace_back(src_workspace: Path, dst_workspace: Path) -> None:
    """Async wrapper for syncing workspace back."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _sync_tree, src_workspace, dst_workspace)


@asynccontextmanager
async def isolated_workspace(
    parent_workspace: str | Path,
) -> AsyncGenerator[tuple[Path, Callable[[], Coroutine[None, None, None]]]]:
    """Context manager that creates an isolated workspace copy.

    Usage:
        async with isolated_workspace("/path/to/parent") as (child_ws, sync_back):
            # Run subagent with child_ws as workspace_path
            ...
            if subagent_won:
                await sync_back()

    Yields:
        (child_workspace_path, sync_back_fn)
    """
    parent_path = Path(parent_workspace)
    tmp_dir = tempfile.mkdtemp(prefix="subagent_ws_", suffix=f"_{parent_path.name}")
    child_path = Path(tmp_dir)

    try:
        loop = asyncio.get_event_loop()
        count = await loop.run_in_executor(None, _clone_workspace, parent_path, child_path)
        logger.info("Isolated workspace created: %s (%d files cloned)", child_path, count)

        async def _sync_back() -> None:
            await _sync_workspace_back(child_path, parent_path)

        yield child_path, _sync_back

    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            logger.debug("Cleaned up isolated workspace: %s", tmp_dir)
        except Exception as e:
            logger.warning("Failed to clean up isolated workspace %s: %s", tmp_dir, e)
