"""Fallback candidate discovery for file search tools.

[INPUT]
- subprocess (POS: git capability probe and git-aware file listing)
- os.walk (POS: bounded filesystem traversal fallback)
- pathlib::Path (POS: path normalization and pattern matching)

[OUTPUT]
- collect_candidate_files: Consistent fallback candidate list for `glob_tool` and `grep_tool`
- is_hidden_path: Hidden-path policy helper

[POS]
Shared fallback discovery layer for file-search tools. Keeps no-ripgrep behavior
bounded and predictable with git-aware ignore handling where available and
root-level ignore files in non-git directories.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_DEFAULT_PRUNED_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".next",
        "dist",
        "build",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".turbo",
        ".cache",
    }
)
_ROOT_IGNORE_FILE_NAMES = (".gitignore", ".ignore", ".fdignore", ".rgignore")


def _pattern_matches(path: Path, root: Path, file_pattern: str) -> bool:
    if file_pattern == "**/*":
        return True
    try:
        rel_path = path.relative_to(root)
    except ValueError:
        rel_path = path
    return rel_path.match(file_pattern) or path.match(file_pattern)


def is_hidden_path(path: Path, root: Path) -> bool:
    """Return True when any path component under root starts with '.'."""
    try:
        rel_path = path.relative_to(root)
    except ValueError:
        rel_path = path
    return any(part.startswith(".") for part in rel_path.parts if part not in {".", ".."})


def _list_git_visible_files(search_root: Path, timeout_seconds: float = 5.0) -> list[Path] | None:
    """Return non-ignored files using git index rules, or None when unavailable."""
    try:
        rev_parse = subprocess.run(
            ["git", "-C", str(search_root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=min(timeout_seconds, 2.0),
            check=False,
        )
        if rev_parse.returncode != 0:
            return None
        repo_root = Path(rev_parse.stdout.strip())
        if not repo_root.exists():
            return None
        try:
            relative_root = search_root.relative_to(repo_root)
        except ValueError:
            return None
        pathspec = "." if str(relative_root) in {"", "."} else relative_root.as_posix()

        ls_files = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
                "--",
                pathspec,
            ],
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        if ls_files.returncode != 0:
            return None

        results: list[Path] = []
        for rel_path in ls_files.stdout.decode("utf-8", errors="replace").split("\x00"):
            if not rel_path:
                continue
            candidate = repo_root / rel_path
            if not candidate.is_file():
                continue
            results.append(candidate)
        return results
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _load_root_ignore_spec(search_root: Path):
    """Load root ignore patterns for non-git fallback, or None."""
    try:
        import pathspec
    except ImportError:
        return None

    patterns: list[str] = []
    for filename in _ROOT_IGNORE_FILE_NAMES:
        ignore_file = search_root / filename
        if not ignore_file.is_file():
            continue
        try:
            for raw_line in ignore_file.read_text(encoding="utf-8", errors="replace").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                patterns.append(line)
        except OSError:
            continue

    if not patterns:
        return None

    try:
        return pathspec.PathSpec.from_lines("gitignore", patterns)
    except Exception:
        return None


def collect_candidate_files(
    *,
    search_root: Path,
    file_pattern: str,
    max_files: int,
    include_hidden: bool,
    include_ignored: bool,
) -> list[Path]:
    """Collect candidate files for fallback engines with bounded cost."""
    if max_files <= 0:
        return []

    if search_root.is_file():
        # Explicit file targets should remain searchable even when hidden.
        return [search_root] if _pattern_matches(search_root, search_root.parent, file_pattern) else []

    candidates: list[Path] = []

    if not include_ignored:
        git_files = _list_git_visible_files(search_root)
        if git_files is not None:
            for file_path in git_files:
                if not include_hidden and is_hidden_path(file_path, search_root):
                    continue
                if not _pattern_matches(file_path, search_root, file_pattern):
                    continue
                candidates.append(file_path)
                if len(candidates) >= max_files:
                    break
            return candidates
    root_ignore_spec = _load_root_ignore_spec(search_root) if not include_ignored else None

    for dirpath, dirnames, filenames in os.walk(search_root, topdown=True):
        current_dir = Path(dirpath)

        if include_hidden:
            hidden_filtered_dirs = dirnames
        else:
            hidden_filtered_dirs = [d for d in dirnames if not d.startswith(".")]

        if include_ignored:
            dirnames[:] = hidden_filtered_dirs
        else:
            visible_dirs = [d for d in hidden_filtered_dirs if d not in _DEFAULT_PRUNED_DIR_NAMES]
            if root_ignore_spec is not None:
                keep_dirs: list[str] = []
                for dirname in visible_dirs:
                    rel_dir = (current_dir / dirname).relative_to(search_root).as_posix()
                    if root_ignore_spec.match_file(rel_dir) or root_ignore_spec.match_file(f"{rel_dir}/"):
                        continue
                    keep_dirs.append(dirname)
                visible_dirs = keep_dirs
            dirnames[:] = visible_dirs

        for filename in filenames:
            if not include_hidden and filename.startswith("."):
                continue

            file_path = current_dir / filename
            if not file_path.is_file():
                continue
            if root_ignore_spec is not None:
                rel_file = file_path.relative_to(search_root).as_posix()
                if root_ignore_spec.match_file(rel_file):
                    continue
            if not _pattern_matches(file_path, search_root, file_pattern):
                continue

            candidates.append(file_path)
            if len(candidates) >= max_files:
                return candidates

    return candidates
