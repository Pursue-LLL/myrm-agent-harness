"""
[INPUT]
git CLI (POS: Repository-aware file listing source)
os.walk (POS: Filesystem fallback enumerator)

[OUTPUT]
WorkspacePathIndexer: lists workspace files as root-relative paths with a short TTL cache.

[POS]
Local workspace file enumerator. Produces bounded relative file lists for higher-level suggestion and indexing features.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 5.0
_CACHE_MAX_FILES = 50_000
_GIT_TIMEOUT_SECONDS = 2.0
_IGNORED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".cache",
        ".next",
        ".nuxt",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "__pycache__",
        "node_modules",
        "venv",
        ".venv",
        "env",
        "dist",
        "build",
        "target",
        "out",
    }
)

_cache_lock = threading.Lock()
_file_cache: dict[str, tuple[float, list[str]]] = {}


class WorkspacePathIndexer:
    """List workspace files as paths relative to a root directory."""

    @classmethod
    def list_files(cls, root: str | Path) -> list[str]:
        """Return cached relevant file paths under ``root``."""

        root_path = Path(root).expanduser().resolve()
        cache_key = str(root_path)
        now = time.monotonic()
        with _cache_lock:
            cached = _file_cache.get(cache_key)
            if cached is not None and now - cached[0] < _CACHE_TTL_SECONDS:
                return cached[1]

        files = cls._git_files(root_path)
        if not files:
            files = cls._walk_files(root_path)

        with _cache_lock:
            _file_cache[cache_key] = (now, files)
        return files

    @classmethod
    def clear_cache(cls, root: str | Path | None = None) -> None:
        """Clear cached listings."""

        with _cache_lock:
            if root is None:
                _file_cache.clear()
                return
            _file_cache.pop(str(Path(root).expanduser().resolve()), None)

    @staticmethod
    def _git_files(root: Path) -> list[str]:
        try:
            top_result = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                capture_output=True,
                timeout=_GIT_TIMEOUT_SECONDS,
                check=False,
            )
            if top_result.returncode != 0:
                return []

            repo_top = Path(top_result.stdout.decode("utf-8", "replace").strip()).resolve()
            list_result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_top),
                    "ls-files",
                    "-z",
                    "--cached",
                    "--others",
                    "--exclude-standard",
                ],
                capture_output=True,
                timeout=_GIT_TIMEOUT_SECONDS,
                check=False,
            )
            if list_result.returncode != 0:
                return []
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.debug("git file listing failed in %s: %s", root, exc)
            return []

        files: list[str] = []
        for raw in list_result.stdout.split(b"\0"):
            if not raw:
                continue
            rel_to_repo = raw.decode("utf-8", "replace")
            abs_file = repo_top / rel_to_repo
            try:
                rel = abs_file.relative_to(root).as_posix()
            except ValueError:
                continue
            if rel.startswith("../") or "/../" in rel:
                continue
            files.append(rel)
            if len(files) >= _CACHE_MAX_FILES:
                break
        return files

    @staticmethod
    def _walk_files(root: Path) -> list[str]:
        files: list[str] = []
        try:
            for current_root, dirnames, filenames in os.walk(root, followlinks=False):
                dirnames[:] = [
                    d for d in dirnames if d not in _IGNORED_DIRS and not d.startswith(".")
                ]
                current = Path(current_root)
                for filename in filenames:
                    if filename.startswith("."):
                        continue
                    try:
                        rel = (current / filename).relative_to(root).as_posix()
                    except ValueError:
                        continue
                    files.append(rel)
                    if len(files) >= _CACHE_MAX_FILES:
                        return files
        except OSError as exc:
            logger.debug("fallback walk failed in %s: %s", root, exc)
        return files
