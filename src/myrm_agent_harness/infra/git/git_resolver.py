"""Pure-python zero-subprocess Git metadata resolver.

Resolves Git branch, commit, and worktree information via direct filesystem reads,
avoiding subprocess fork overhead and dependencies on Git binary CLI in sandboxes.

[INPUT]
- workspace_dir: str | Path | None (Directory to inspect, defaults to cwd)

[OUTPUT]
- GitMetadata: dataclass containing branch, commit, is_worktree, and is_detached
- resolve_git_branch: convenience function returning branch name or None

[POS]
Infra layer git resolution utility. Thread-safe with stat mtime debounce cache.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class GitMetadata:
    """Resolved Git repository metadata."""

    branch: str | None = None
    commit: str | None = None
    is_worktree: bool = False
    is_detached: bool = False


_CACHE_LOCK = threading.Lock()
_METADATA_CACHE: dict[str, tuple[float, GitMetadata]] = {}
_MAX_CACHE_SIZE = 64


def _find_git_dir(workspace_path: Path) -> tuple[Path | None, bool]:
    """Locate the actual git directory, handling both standard repos and linked worktrees."""
    git_entry = workspace_path / ".git"
    try:
        if not git_entry.exists():
            return None, False

        if git_entry.is_dir():
            return git_entry, False

        if git_entry.is_file():
            # Linked worktree: .git is a file containing "gitdir: <path>"
            content = git_entry.read_text(encoding="utf-8", errors="ignore").strip()
            if content.startswith("gitdir:"):
                raw_path = content[len("gitdir:") :].strip()
                target_path = Path(raw_path)
                if not target_path.is_absolute():
                    target_path = (workspace_path / target_path).resolve()
                if target_path.is_dir():
                    return target_path, True
    except (FileNotFoundError, PermissionError, NotADirectoryError, OSError):
        return None, False

    return None, False


def _read_ref_commit(git_dir: Path, ref_path: str) -> str | None:
    """Try to read the commit hash for a symbolic ref (e.g., refs/heads/main)."""
    target = git_dir / ref_path
    try:
        if target.is_file():
            commit = target.read_text(encoding="utf-8", errors="ignore").strip()
            if len(commit) == 40 and all(c in "0123456789abcdefABCDEF" for c in commit):
                return commit
    except (FileNotFoundError, PermissionError, OSError):
        pass

    # Fallback to packed-refs if available
    packed_refs = git_dir / "packed-refs"
    try:
        if packed_refs.is_file():
            for line in packed_refs.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line.startswith("#") or line.startswith("^"):
                    continue
                parts = line.split(" ", 1)
                if len(parts) == 2 and parts[1] == ref_path:
                    return parts[0]
    except (FileNotFoundError, PermissionError, OSError):
        pass

    return None


def resolve_git_metadata(workspace_dir: str | Path | None = None) -> GitMetadata:
    """Resolve Git metadata using pure filesystem reads with mtime debouncing.

    Args:
        workspace_dir: Directory to inspect. Defaults to current working directory.

    Returns:
        GitMetadata object with branch, commit, and worktree flags.
    """
    try:
        root_path = Path(workspace_dir).resolve() if workspace_dir else Path.cwd().resolve()
    except Exception:
        return GitMetadata()

    cache_key = str(root_path)

    git_dir, is_worktree = _find_git_dir(root_path)
    if git_dir is None:
        return GitMetadata()

    head_path = git_dir / "HEAD"
    try:
        stat_res = head_path.stat()
        current_mtime = stat_res.st_mtime
    except (FileNotFoundError, PermissionError, OSError):
        return GitMetadata()

    # Check in-memory debounce cache
    with _CACHE_LOCK:
        if cache_key in _METADATA_CACHE:
            cached_mtime, cached_meta = _METADATA_CACHE[cache_key]
            if cached_mtime == current_mtime:
                return cached_meta

    try:
        content = head_path.read_text(encoding="utf-8", errors="ignore").strip()
    except (FileNotFoundError, PermissionError, OSError):
        return GitMetadata()

    if not content:
        return GitMetadata()

    branch: str | None = None
    commit: str | None = None
    is_detached = False

    if content.startswith("ref:"):
        # Symbolic reference (e.g. ref: refs/heads/main)
        ref_full = content[len("ref:") :].strip()
        prefix = "refs/heads/"
        if ref_full.startswith(prefix):
            branch = ref_full[len(prefix) :].strip()
        else:
            branch = ref_full
        commit = _read_ref_commit(git_dir, ref_full)
    elif len(content) >= 7 and all(c in "0123456789abcdefABCDEF" for c in content):
        # Detached HEAD (raw commit hash)
        commit = content
        branch = f"(detached:{content[:7]})"
        is_detached = True

    resolved = GitMetadata(
        branch=branch,
        commit=commit,
        is_worktree=is_worktree,
        is_detached=is_detached,
    )

    with _CACHE_LOCK:
        if len(_METADATA_CACHE) >= _MAX_CACHE_SIZE:
            _METADATA_CACHE.clear()
        _METADATA_CACHE[cache_key] = (current_mtime, resolved)

    return resolved


def resolve_git_branch(workspace_dir: str | Path | None = None) -> str | None:
    """Convenience helper returning just the branch name or None.

    Args:
        workspace_dir: Directory to inspect. Defaults to current working directory.

    Returns:
        Branch name string (or formatted detached tag) or None.
    """
    return resolve_git_metadata(workspace_dir).branch
