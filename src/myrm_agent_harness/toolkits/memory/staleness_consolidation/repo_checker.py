"""Workspace repository fact invalidation checker (Item 158).

[INPUT]
- MemoryItemProfile records and workspace root directory.

[OUTPUT]
- RepoAssertionCheckResult and updated item invalidation status.

[POS]
- Invalidation checker in myrm_agent_harness/toolkits/memory/staleness_consolidation/.
"""

from __future__ import annotations

import os
from pathlib import Path

from .models import MemoryItemProfile, RepoAssertionCheckResult


class RepoFactInvalidationChecker:
    """Verifies that codebase assumptions, file paths, and dependencies in memory still hold true."""

    def __init__(self, workspace_root: str | None = None) -> None:
        self.workspace_root = workspace_root

    def _resolve_path(self, rel_path: str, base_dir: str) -> Path:
        """Resolve a relative workspace path safely within base directory."""
        clean_rel = rel_path.lstrip("/\\")
        return Path(base_dir).resolve() / clean_rel

    def check_item(
        self,
        item: MemoryItemProfile,
        workspace_dir: str | None = None,
    ) -> RepoAssertionCheckResult:
        """Verify referenced paths and assertion expressions against current workspace state."""
        target_dir = workspace_dir or self.workspace_root
        if not target_dir or not os.path.isdir(target_dir):
            return RepoAssertionCheckResult(
                memory_id=item.memory_id,
                is_valid=True,
                diagnostic="Workspace directory not provided or unreachable; skipped check.",
            )

        missing_paths: list[str] = []
        failed_assertions: list[str] = []

        # 1. Verify existence of referenced paths
        for path_ref in item.referenced_paths:
            resolved = self._resolve_path(path_ref, target_dir)
            if not resolved.exists():
                missing_paths.append(path_ref)

        # 2. Verify assertion rules
        for assertion in item.referenced_assertions:
            # Format: "contains:<file>:<content>"
            if assertion.startswith("contains:"):
                parts = assertion.split(":", 2)
                if len(parts) == 3:
                    _, file_rel, expected_content = parts
                    file_path = self._resolve_path(file_rel, target_dir)
                    if not file_path.is_file():
                        failed_assertions.append(
                            f"Target file {file_rel} missing for assertion {assertion}"
                        )
                    else:
                        try:
                            text = file_path.read_text(encoding="utf-8", errors="ignore")
                            if expected_content not in text:
                                failed_assertions.append(
                                    f"File {file_rel} does not contain '{expected_content}'"
                                )
                        except OSError as exc:
                            failed_assertions.append(
                                f"Failed to read {file_rel}: {exc}"
                            )
            # Format: "missing:<file>"
            elif assertion.startswith("missing:"):
                file_rel = assertion[len("missing:") :]
                file_path = self._resolve_path(file_rel, target_dir)
                if file_path.exists():
                    failed_assertions.append(
                        f"Expected {file_rel} to be missing, but it exists"
                    )

        is_valid = len(missing_paths) == 0 and len(failed_assertions) == 0

        diagnostic = "All referenced workspace paths and assertions verified valid."
        if not is_valid:
            reasons: list[str] = []
            if missing_paths:
                reasons.append(f"Missing paths: {', '.join(missing_paths)}")
            if failed_assertions:
                reasons.append(f"Failed assertions: {'; '.join(failed_assertions)}")
            diagnostic = " | ".join(reasons)

            # Update item status
            item.status = "invalidated"
            item.invalidation_reason = diagnostic

        return RepoAssertionCheckResult(
            memory_id=item.memory_id,
            is_valid=is_valid,
            missing_paths=missing_paths,
            failed_assertions=failed_assertions,
            diagnostic=diagnostic,
        )

    def check_items(
        self,
        items: list[MemoryItemProfile],
        workspace_dir: str | None = None,
    ) -> list[RepoAssertionCheckResult]:
        """Perform batch validation across multiple memory profiles."""
        return [self.check_item(it, workspace_dir=workspace_dir) for it in items]
