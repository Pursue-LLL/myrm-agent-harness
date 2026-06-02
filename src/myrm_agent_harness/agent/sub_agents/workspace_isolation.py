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


def _clone_workspace(src: Path, dst: Path) -> int:
    """Recursively clone src into dst. Returns count of files.

    Uses shutil.copytree which automatically utilizes OS-level Copy-on-Write
    (like APFS clonefile on macOS or Btrfs reflinks on Linux) when available.
    This provides true isolation (unlike hardlinks which leak in-place edits)
    while maintaining near-instant creation speed on modern filesystems.
    """
    shutil.copytree(src, dst, dirs_exist_ok=True)
    # Return approximate count for logging
    return sum(1 for _ in dst.rglob("*") if _.is_file())


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
