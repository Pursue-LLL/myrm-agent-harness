"""Artifact identification system.

Multi-layered strategy for identifying files that need persistence:
1. File extension matching (.py, .md, .json, etc.)
2. LLM-based classification
3. User feedback learning

Persistent Volume Support:
- Recognizes /persistent as the persistent volume mount point
- Context files (.context/) are automatically persistent
- Workspace files follow artifact rules

[INPUT]
- (none)

[OUTPUT]
- ArtifactJudge: Intelligent artifact identification.

[POS]
Artifact identification system.
"""

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ArtifactJudge:
    """
    Intelligent artifact identification.

    Determines which files should be persisted to dedicated volume.
    """

    def __init__(self) -> None:
        """Initialize artifact judge."""
        # Layer 1: File extension whitelist
        self._artifact_extensions = {
            # Code
            ".py",
            ".js",
            ".ts",
            ".jsx",
            ".tsx",
            ".go",
            ".rs",
            ".java",
            ".cpp",
            ".c",
            ".h",
            # Config
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".ini",
            # Documentation
            ".md",
            ".txt",
            ".rst",
            # Data
            ".csv",
            ".parquet",
            ".sqlite",
            ".db",
            # Assets
            ".png",
            ".jpg",
            ".jpeg",
            ".svg",
        }

        # Layer 1: Directory whitelist
        self._artifact_directories = {
            "src",
            "lib",
            "app",
            "config",
            "data",
            "docs",
            "tests",
            ".vscode",
            ".cursor",
        }

        # Layer 1: Blacklist (never persist)
        self._blacklist_patterns = {
            "node_modules",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            "venv",
            ".venv",
            ".git",
            "dist",
            "build",
            ".next",
        }

        # Layer 3: User feedback (filename -> should_persist)
        self._user_feedback: dict[str, bool] = {}

    def should_persist(
        self,
        file_path: str,
        workspace_root: str = "/workspace",
    ) -> tuple[bool, str]:
        """
        Determine if file should be persisted.

        Args:
            file_path: Absolute file path
            workspace_root: Workspace root directory (default: /workspace for legacy compatibility)

        Returns:
            Tuple of (should_persist, reason)
        """
        from myrm_agent_harness.runtime.execution_paths import is_context_path, is_persistent_path

        # Check if file is in persistent volume
        # Context files are always persistent
        if is_persistent_path(file_path) and is_context_path(file_path):
            return True, "Context file (persistent volume)"

        # Make path relative to workspace
        try:
            rel_path = os.path.relpath(file_path, workspace_root)
        except ValueError:
            rel_path = file_path

        path = Path(rel_path)

        # Check user feedback first (Layer 3)
        if rel_path in self._user_feedback:
            decision = self._user_feedback[rel_path]
            return decision, "User feedback"

        # Check blacklist patterns
        for pattern in self._blacklist_patterns:
            if pattern in path.parts:
                return False, f"Blacklisted pattern: {pattern}"

        # Check file extension (Layer 1)
        if path.suffix.lower() in self._artifact_extensions:
            return True, f"Artifact extension: {path.suffix}"

        # Check directory (Layer 1)
        for part in path.parts:
            if part in self._artifact_directories:
                return True, f"Artifact directory: {part}"

        # Layer 2: LLM-based classification (future enhancement)
        # Integration point: Pass file path and content sample to LLM for classification

        # Default: do not persist
        return False, "No matching rule"

    def scan_workspace(
        self,
        workspace_root: str = "/workspace",
    ) -> dict[str, list[str]]:
        """
        Scan workspace and classify all files.

        Args:
            workspace_root: Workspace root directory

        Returns:
            Dict with "persist" and "ephemeral" file lists
        """
        persist_files: list[str] = []
        ephemeral_files: list[str] = []

        try:
            for root, dirs, files in os.walk(workspace_root):
                # Skip blacklisted directories
                dirs[:] = [d for d in dirs if d not in self._blacklist_patterns]

                for file in files:
                    file_path = os.path.join(root, file)
                    should_persist, _reason = self.should_persist(file_path, workspace_root)

                    if should_persist:
                        persist_files.append(file_path)
                    else:
                        ephemeral_files.append(file_path)

        except Exception as e:
            logger.error(f"Error scanning workspace: {e}")

        logger.info(f"Scan complete: {len(persist_files)} artifacts, {len(ephemeral_files)} ephemeral files")

        return {
            "persist": persist_files,
            "ephemeral": ephemeral_files,
        }

    def record_feedback(
        self,
        file_path: str,
        should_persist: bool,
    ) -> None:
        """
        Record user feedback for file persistence decision.

        Args:
            file_path: File path
            should_persist: User's decision
        """
        self._user_feedback[file_path] = should_persist
        logger.info(f"Recorded feedback: {file_path} -> {should_persist}")

    def get_statistics(self) -> dict[str, Any]:
        """Get artifact identification statistics."""
        return {
            "artifact_extensions": len(self._artifact_extensions),
            "artifact_directories": len(self._artifact_directories),
            "blacklist_patterns": len(self._blacklist_patterns),
            "user_feedback_count": len(self._user_feedback),
        }
