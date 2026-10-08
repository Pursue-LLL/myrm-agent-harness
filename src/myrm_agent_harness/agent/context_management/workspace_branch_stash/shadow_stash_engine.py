"""Engine managing lightweight shadow stash capture and checkout restoration in workspace sandbox.

[INPUT]
- relative_paths: List[str] targeting files to capture
- workspace_root: str directory root of the sandbox workspace
- target_snapshot: BranchWorkspaceSnapshot containing files to restore

[OUTPUT]
- ShadowStashEngine: Class managing file capture, conflict checking, and disk checkout.

[POS]
Engine managing lightweight shadow stash capture and checkout restoration in workspace sandbox.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .workspace_stash_types import (
    BranchWorkspaceSnapshot,
    FileStashKind,
    ShadowStashFileRecord,
    WorkspaceStashConflictWarning,
)


class ShadowStashEngine:
    """Handles non-destructive file capture, conflict inspection, and workspace snapshot checkout."""

    @classmethod
    def compute_sha256(cls, content: str) -> str:
        """Calculate SHA-256 checksum for text content."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    @classmethod
    def capture_workspace_snapshot(
        cls,
        workspace_root: str,
        session_id: str,
        branch_name: str,
        relative_paths: List[str],
    ) -> BranchWorkspaceSnapshot:
        """Capture specified relative files into a persistent branch workspace snapshot."""
        root = Path(workspace_root)
        records: Dict[str, ShadowStashFileRecord] = {}

        for rel_path in sorted(relative_paths):
            target_path = root / rel_path
            if target_path.exists() and target_path.is_file():
                text = target_path.read_text(encoding="utf-8")
                checksum = cls.compute_sha256(text)
                records[rel_path] = ShadowStashFileRecord(
                    relative_path=rel_path,
                    file_stash_kind=FileStashKind.MODIFIED,
                    content_text=text,
                    sha256_hash=checksum,
                    size_bytes=len(text.encode("utf-8")),
                    captured_at_iso=datetime.now(timezone.utc).isoformat(),
                )

        all_hashes = "".join(r.sha256_hash for r in records.values())
        snapshot_hash = hashlib.sha256(f"{branch_name}:{all_hashes}".encode("utf-8")).hexdigest()[:16]

        return BranchWorkspaceSnapshot(
            session_id=session_id,
            branch_name=branch_name,
            stashed_files=records,
            snapshot_hash=snapshot_hash,
            is_pristine=len(records) == 0,
        )

    @classmethod
    def detect_dirty_conflicts(
        cls,
        workspace_root: str,
        target_snapshot: BranchWorkspaceSnapshot,
        source_snapshot: Optional[BranchWorkspaceSnapshot] = None,
    ) -> List[WorkspaceStashConflictWarning]:
        """Pre-flight check detecting whether current disk files conflict with target branch snapshot."""
        root = Path(workspace_root)
        warnings: List[WorkspaceStashConflictWarning] = []

        for rel_path, target_record in target_snapshot.stashed_files.items():
            curr_path = root / rel_path
            if curr_path.exists() and curr_path.is_file():
                curr_text = curr_path.read_text(encoding="utf-8")
                curr_hash = cls.compute_sha256(curr_text)
                
                # Check if file has diverged between source branch and target branch
                has_diverged = False
                if source_snapshot and rel_path in source_snapshot.stashed_files:
                    source_hash = source_snapshot.stashed_files[rel_path].sha256_hash
                    if source_hash != target_record.sha256_hash:
                        has_diverged = True
                elif curr_hash != target_record.sha256_hash:
                    has_diverged = True

                if has_diverged:
                    warnings.append(
                        WorkspaceStashConflictWarning(
                            relative_path=rel_path,
                            source_branch_hash=curr_hash,
                            target_branch_hash=target_record.sha256_hash,
                            conflict_reason=f"File '{rel_path}' on disk differs from target branch baseline",
                        )
                    )

        return warnings

    @classmethod
    def apply_workspace_snapshot(
        cls,
        workspace_root: str,
        target_snapshot: BranchWorkspaceSnapshot,
        previous_tracked_paths: Optional[List[str]] = None,
    ) -> int:
        """Restore target branch snapshot files onto disk and purge source-exclusive artifacts."""
        root = Path(workspace_root)
        root.mkdir(parents=True, exist_ok=True)
        restored_count = 0

        target_paths_set = set(target_snapshot.stashed_files.keys())

        # Purge files present in previous branch but absent in target branch
        if previous_tracked_paths:
            for old_path in previous_tracked_paths:
                if old_path not in target_paths_set:
                    file_to_remove = root / old_path
                    if file_to_remove.exists() and file_to_remove.is_file():
                        file_to_remove.unlink()

        # Write target branch files
        for rel_path, record in target_snapshot.stashed_files.items():
            file_path = root / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(record.content_text, encoding="utf-8")
            restored_count += 1

        return restored_count
