"""Workspace directory validation and lightweight Git metadata inspector.

[INPUT]
- launcher_types: None directly (pure path & metadata discovery).

[OUTPUT]
- WorkspaceMetadataInspector: Safely validates workspace directories and
  detects git branch and repository root without heavyweight blocking operations.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.project_bound_launcher
- Module: workspace_metadata_inspector.py
"""

import os
from pathlib import Path
from typing import Optional, Tuple


class WorkspaceMetadataInspector:
    """Lightweight inspector for verifying workspace paths and reading git metadata."""

    def __init__(self, sandbox_root: Optional[str] = None) -> None:
        self._sandbox_root = sandbox_root

    def validate_workspace_path(self, path_str: str) -> Tuple[bool, str]:
        """Validates that a workspace path is syntactically sound and non-empty.

        Args:
            path_str: Target workspace directory string.

        Returns:
            Tuple of (is_valid, resolved_path_or_reason).
        """
        if not path_str or not path_str.strip():
            return False, "Workspace path cannot be empty or whitespace."

        cleaned = path_str.strip()
        # Disallow insecure traversal escaping
        if ".." in cleaned.split(os.sep):
            return False, f"Insecure path traversal detected in '{path_str}'."

        try:
            norm_path = os.path.abspath(cleaned)
            if self._sandbox_root:
                norm_sandbox = os.path.abspath(self._sandbox_root)
                if not norm_path.startswith(norm_sandbox):
                    return False, f"Path '{norm_path}' is outside sandbox root '{norm_sandbox}'."
            return True, norm_path
        except Exception as exc:
            return False, f"Invalid path syntax: {exc}"

    def inspect_git_metadata(self, workspace_path: str) -> Tuple[str, str]:
        """Discovers the git branch and repository root via lightweight filesystem inspection.

        Avoids blocking subprocess invocations by directly reading the .git/HEAD file.

        Args:
            workspace_path: Absolute or relative directory path.

        Returns:
            Tuple of (git_branch, git_repo_root). Empty strings if not a git repository.
        """
        try:
            curr = Path(workspace_path).resolve()
        except Exception:
            return "", ""

        # Walk upward up to 5 levels to locate .git directory
        levels_checked = 0
        while levels_checked < 5:
            git_entry = curr / ".git"
            if git_entry.exists():
                repo_root = str(curr)
                branch = self._read_head_branch(git_entry)
                return branch, repo_root

            parent = curr.parent
            if parent == curr:
                break
            curr = parent
            levels_checked += 1

        return "", ""

    def _read_head_branch(self, git_entry: Path) -> str:
        """Reads git branch name from .git/HEAD file."""
        head_file: Optional[Path] = None
        if git_entry.is_dir():
            head_file = git_entry / "HEAD"
        elif git_entry.is_file():
            # Submodule or worktree .git file containing "gitdir: ..."
            try:
                content = git_entry.read_text(encoding="utf-8").strip()
                if content.startswith("gitdir:"):
                    gitdir = content.split(":", 1)[1].strip()
                    resolved_gitdir = (git_entry.parent / gitdir).resolve()
                    head_file = resolved_gitdir / "HEAD"
            except Exception:
                return "detached"

        if head_file and head_file.exists():
            try:
                line = head_file.read_text(encoding="utf-8").strip()
                if line.startswith("ref: refs/heads/"):
                    return line[len("ref: refs/heads/") :]
                elif line:
                    return line[:8]  # Detached commit short hash
            except Exception:
                return "unknown"

        return "main"
