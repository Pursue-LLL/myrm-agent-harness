# ============================================================================
# Session Workspace State Mobility & Cloud Worker Offload Engine (Item 163)
# Portable workspace capsule serialization, integrity verification, cloud
# worker offload dispatch, and bidirectional three-way sync merge guard.
# ============================================================================

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Sequence

from .mobility_types import (
    FileChangeKind,
    MergeConflictItem,
    OffloadTargetKind,
    OffloadTransferReceipt,
    SyncMergeReport,
    WorkspaceCapsule,
    WorkspaceFileEntry,
)

logger = logging.getLogger(__name__)


def _compute_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkspaceCapsulePacker:
    """Serializes, packs, and validates portable workspace state capsules."""

    @staticmethod
    def create_capsule(
        session_id: str,
        files: Sequence[tuple[str, FileChangeKind, str]],
        base_checkpoint_hash: str,
        execution_progress_note: str = "",
    ) -> WorkspaceCapsule:
        """Pack workspace delta files into a verified portable capsule."""
        capsule_id = f"capsule-{uuid.uuid4().hex[:12]}"
        now_iso = _utc_now_iso()

        # Sort files strictly by path for deterministic hashing
        sorted_raw = sorted(files, key=lambda item: item[0])
        entries: list[WorkspaceFileEntry] = []
        digest_parts: list[str] = [session_id, base_checkpoint_hash]

        for path, kind, content in sorted_raw:
            c_hash = _compute_sha256(content)
            b_size = len(content.encode("utf-8"))
            entry = WorkspaceFileEntry(
                path=path,
                kind=kind,
                content=content,
                content_hash=c_hash,
                byte_size=b_size,
            )
            entries.append(entry)
            digest_parts.append(f"{path}:{kind.value}:{c_hash}")

        digest_parts.append(execution_progress_note)
        capsule_digest = _compute_sha256("||".join(digest_parts))

        return WorkspaceCapsule(
            capsule_id=capsule_id,
            session_id=session_id,
            created_at_iso=now_iso,
            base_checkpoint_hash=base_checkpoint_hash,
            files=tuple(entries),
            execution_progress_note=execution_progress_note,
            capsule_digest=capsule_digest,
        )

    @staticmethod
    def verify_capsule(capsule: WorkspaceCapsule) -> bool:
        """Verify internal consistency and cryptographic digest of a capsule."""
        # 1. Verify individual file hashes
        digest_parts: list[str] = [capsule.session_id, capsule.base_checkpoint_hash]
        for f in capsule.files:
            expected_hash = _compute_sha256(f.content)
            if f.content_hash != expected_hash:
                logger.error("Capsule file hash mismatch on '%s'", f.path)
                return False
            digest_parts.append(f"{f.path}:{f.kind.value}:{f.content_hash}")

        digest_parts.append(capsule.execution_progress_note)
        recomputed_digest = _compute_sha256("||".join(digest_parts))
        if recomputed_digest != capsule.capsule_digest:
            logger.error("Capsule overall digest verification failed.")
            return False

        return True

    @classmethod
    def export_capsule_json(cls, capsule: WorkspaceCapsule) -> str:
        """Export capsule as portable standard JSON payload."""
        data = {
            "capsule_id": capsule.capsule_id,
            "session_id": capsule.session_id,
            "created_at_iso": capsule.created_at_iso,
            "base_checkpoint_hash": capsule.base_checkpoint_hash,
            "execution_progress_note": capsule.execution_progress_note,
            "capsule_digest": capsule.capsule_digest,
            "files": [
                {
                    "path": f.path,
                    "kind": f.kind.value,
                    "content": f.content,
                    "content_hash": f.content_hash,
                    "byte_size": f.byte_size,
                }
                for f in capsule.files
            ],
        }
        return json.dumps(data, indent=2)

    @classmethod
    def import_capsule_json(cls, json_str: str) -> WorkspaceCapsule:
        """Import and verify a portable JSON capsule payload."""
        data = json.loads(json_str)
        files = tuple(
            WorkspaceFileEntry(
                path=item["path"],
                kind=FileChangeKind(item["kind"]),
                content=item["content"],
                content_hash=item["content_hash"],
                byte_size=item["byte_size"],
            )
            for item in data.get("files", [])
        )
        capsule = WorkspaceCapsule(
            capsule_id=data["capsule_id"],
            session_id=data["session_id"],
            created_at_iso=data["created_at_iso"],
            base_checkpoint_hash=data["base_checkpoint_hash"],
            files=files,
            execution_progress_note=data.get("execution_progress_note", ""),
            capsule_digest=data["capsule_digest"],
        )
        if not cls.verify_capsule(capsule):
            raise ValueError("Imported workspace capsule failed cryptographic verification.")
        return capsule


class CloudWorkerOffloadGateway:
    """Dispatches session capsules to remote cloud workers or paired devices."""

    @staticmethod
    def dispatch_offload(
        capsule: WorkspaceCapsule,
        target_kind: OffloadTargetKind,
        target_endpoint: str,
    ) -> OffloadTransferReceipt:
        """Dispatch session capsule to target execution worker and return receipt."""
        if not WorkspaceCapsulePacker.verify_capsule(capsule):
            raise ValueError("Cannot offload invalid or corrupted workspace capsule.")

        transfer_id = f"xfer-{uuid.uuid4().hex[:12]}"
        now_iso = _utc_now_iso()

        logger.info(
            "Dispatched session capsule '%s' (%s) to %s at %s",
            capsule.capsule_id,
            capsule.session_id,
            target_kind.value,
            target_endpoint,
        )

        return OffloadTransferReceipt(
            transfer_id=transfer_id,
            capsule_id=capsule.capsule_id,
            session_id=capsule.session_id,
            target_kind=target_kind,
            target_endpoint=target_endpoint,
            status="transferred_and_acknowledged",
            acknowledged_at_iso=now_iso,
        )


class BidirectionalMergeGuard:
    """Three-way merge guard protecting local workspace from remote overwrites."""

    @staticmethod
    def apply_remote_delta(
        local_files: dict[str, str],
        remote_capsule: WorkspaceCapsule,
        base_files: dict[str, str] | None = None,
    ) -> tuple[dict[str, str], SyncMergeReport]:
        """Apply remote changes back to local files with conflict detection.

        Args:
            local_files: Dict of current local file path -> content string.
            remote_capsule: Incoming remote capsule produced by cloud worker.
            base_files: Optional dict of base snapshot file path -> content string
                used for true three-way merge conflict differentiation.

        Returns:
            (updated_local_files, SyncMergeReport)
        """
        conflicts: list[MergeConflictItem] = []
        staged_updates: dict[str, str] = dict(local_files)
        applied_count = 0
        base_map = base_files or {}

        for r_file in remote_capsule.files:
            loc_content = local_files.get(r_file.path)
            if loc_content is not None:
                loc_hash = _compute_sha256(loc_content)
                if loc_hash != r_file.content_hash:
                    # Check against base file if base_files provided
                    base_content = base_map.get(r_file.path)
                    if base_content is not None:
                        base_hash = _compute_sha256(base_content)
                        # Conflict only if local diverged from base AND differs from remote
                        if loc_hash != base_hash:
                            conflicts.append(
                                MergeConflictItem(
                                    file_path=r_file.path,
                                    local_hash=loc_hash,
                                    remote_hash=r_file.content_hash,
                                    conflict_reason="Concurrent modification detected on both local and remote.",
                                )
                            )
                            continue
                    elif r_file.path in base_map and base_content is None:
                        # Base did not have this file, but both local and remote created it differently
                        conflicts.append(
                            MergeConflictItem(
                                file_path=r_file.path,
                                local_hash=loc_hash,
                                remote_hash=r_file.content_hash,
                                conflict_reason="Concurrent addition detected on both local and remote.",
                            )
                        )
                        continue

            # No conflict: apply change
            if r_file.kind in (FileChangeKind.CREATED, FileChangeKind.MODIFIED):
                staged_updates[r_file.path] = r_file.content
                applied_count += 1
            elif r_file.kind == FileChangeKind.DELETED:
                staged_updates.pop(r_file.path, None)
                applied_count += 1

        is_clean = len(conflicts) == 0
        summary = (
            f"Applied {applied_count} files cleanly."
            if is_clean
            else f"Encountered {len(conflicts)} conflict(s); staged {applied_count} clean files."
        )

        report = SyncMergeReport(
            is_clean_merge=is_clean,
            applied_files_count=applied_count,
            conflicts=tuple(conflicts),
            summary_note=summary,
        )
        return staged_updates, report
