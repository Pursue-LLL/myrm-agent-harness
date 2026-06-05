"""High-performance workspace file indexer.

[INPUT]
- (none)

[OUTPUT]
- WorkspaceFileIndexer: Provides high-speed file listing for a given workspace.

[POS]
Generic workspace indexing utility. Dual-engine (Git / OS Walk) for maximum performance.
"""

from __future__ import annotations

import logging
import os
import subprocess

logger = logging.getLogger(__name__)

_DEFAULT_IGNORED_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        "venv",
        ".venv",
        "env",
        ".env",
        ".idea",
        ".vscode",
        "dist",
        "build",
        "target",
        "out",
        ".next",
        ".nuxt",
    }
)

_MAX_FALLBACK_FILES = 50000
_GIT_TIMEOUT_SECONDS = 2.0


class WorkspaceFileIndexer:
    """High-performance indexer to retrieve a list of relative file paths in a workspace."""

    @classmethod
    def list_all_files(cls, workspace: str) -> list[str]:
        """List all relevant files in the workspace (relative paths).

        Prioritizes `git ls-files` if applicable, falling back to a tuned `os.walk`.
        """
        resolved = os.path.realpath(os.path.expanduser(workspace))

        git_dir = os.path.join(resolved, ".git")
        if os.path.isdir(git_dir):
            try:
                # Use git to get all tracked and untracked (but not ignored) files
                # -z uses null byte separation to handle spaces in filenames
                result = subprocess.run(
                    ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                    cwd=resolved,
                    capture_output=True,
                    timeout=_GIT_TIMEOUT_SECONDS,
                    check=True,
                )
                if result.stdout:
                    files = result.stdout.split(b"\0")
                    # decode and filter empty strings
                    decoded_files = [f.decode("utf-8", errors="replace") for f in files if f]
                    # git ls-files uses '/' for separators regardless of OS
                    # we convert to OS separator if needed
                    if os.sep != "/":
                        decoded_files = [f.replace("/", os.sep) for f in decoded_files]
                    return decoded_files
            except Exception as e:
                logger.debug("git ls-files failed in %s: %s, falling back to os.walk", resolved, e)

        # Fallback to os.walk
        return cls._fallback_walk(resolved)

    @classmethod
    def _fallback_walk(cls, root_real: str) -> list[str]:
        files: list[str] = []
        for current_root, dirs, filenames in os.walk(root_real):
            # In-place filtering of directories
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in _DEFAULT_IGNORED_DIRS]

            for fname in filenames:
                if fname.startswith("."):
                    continue

                if len(files) >= _MAX_FALLBACK_FILES:
                    logger.debug("Reached max fallback files %d in %s", _MAX_FALLBACK_FILES, root_real)
                    return files

                full_path = os.path.join(current_root, fname)
                rel = os.path.relpath(full_path, root_real)
                files.append(rel)

        return files
