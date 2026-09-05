"""Automatic staging and LRU preservation for unwritten deliverables.

Saves unpersisted substantive deliverables generated in assistant responses
into a sandboxed staging directory (.myrm/staged_artifacts/) as drafts when
completion is forced or write tools are skipped, preventing asset loss.

[INPUT]
- workspace_root: Path or string representing agent workspace root
- deliverables: list of UnwrittenDeliverable objects

[OUTPUT]
- stage_unwritten_deliverables(): list of StagedArtifactMeta describing saved drafts

[POS]
Harness middleware asset protector; invoked from CompletionGuard when unwritten
deliverables are detected at forced completion.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .deliverable_write_verifier import UnwrittenDeliverable

logger = logging.getLogger(__name__)

STAGED_ARTIFACTS_DIR: str = ".myrm/staged_artifacts"
MAX_STAGED_ARTIFACTS_LIMIT: int = 20


@dataclass(frozen=True)
class StagedArtifactMeta:
    """Metadata describing an automatically staged draft deliverable."""

    artifact_id: str
    filename: str
    relative_path: str
    full_path: str
    language: str
    size_bytes: int
    line_count: int
    created_at: str
    original_hint: str | None

    def to_dict(self) -> dict[str, str | int | None]:
        """Convert metadata to dictionary for message serialization."""
        return asdict(self)


def _sanitize_filename(name: str) -> str:
    """Sanitize name to prevent path traversal while keeping filename meaningful."""
    clean = Path(name).name.strip()
    return "".join(c if c.isalnum() or c in (".", "_", "-") else "_" for c in clean)


def _prune_old_staged_artifacts(staged_dir: Path, max_keep: int = MAX_STAGED_ARTIFACTS_LIMIT) -> None:
    """Enforce LRU capacity constraint by removing oldest staged files."""
    try:
        if not staged_dir.exists():
            return
        files = [p for p in staged_dir.iterdir() if p.is_file()]
        if len(files) <= max_keep:
            return

        files.sort(key=lambda p: p.stat().st_mtime)
        excess_count = len(files) - max_keep
        for f in files[:excess_count]:
            try:
                f.unlink(missing_ok=True)
            except OSError as e:
                logger.warning("[DeliverableAutoStaging] Failed to prune aged draft %s: %s", f, e)
    except Exception as e:
        logger.warning("[DeliverableAutoStaging] Error while pruning staged drafts: %s", e)


def stage_unwritten_deliverables(
    workspace_root: str | Path,
    deliverables: list[UnwrittenDeliverable],
) -> list[StagedArtifactMeta]:
    """Persist unwritten deliverables to .myrm/staged_artifacts/ in the sandbox workspace.

    Returns metadata list for serialization and UI presentation.
    """
    if not deliverables:
        return []

    root_path = Path(workspace_root).resolve()
    target_dir = root_path / STAGED_ARTIFACTS_DIR

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error("[DeliverableAutoStaging] Cannot create staging dir %s: %s", target_dir, e)
        return []

    staged_results: list[StagedArtifactMeta] = []
    now = datetime.now(timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")
    iso_str = now.isoformat()

    for idx, item in enumerate(deliverables):
        try:
            content_bytes = item.content.encode("utf-8")
            content_hash = hashlib.sha256(content_bytes).hexdigest()[:8]

            if item.filename_hint:
                base_name = _sanitize_filename(item.filename_hint)
            else:
                base_name = f"draft_{item.language}_{idx + 1}{item.suggested_ext}"

            staged_filename = f"{ts_str}_{content_hash}_{base_name}"
            staged_file_path = target_dir / staged_filename

            staged_file_path.write_bytes(content_bytes)

            meta = StagedArtifactMeta(
                artifact_id=f"staged_{content_hash}",
                filename=staged_filename,
                relative_path=f"{STAGED_ARTIFACTS_DIR}/{staged_filename}",
                full_path=str(staged_file_path),
                language=item.language,
                size_bytes=len(content_bytes),
                line_count=item.line_count,
                created_at=iso_str,
                original_hint=item.filename_hint,
            )
            staged_results.append(meta)
            logger.info(
                "[DeliverableAutoStaging] Successfully staged unwritten deliverable '%s' -> %s",
                item.filename_hint or base_name,
                staged_file_path,
            )
        except Exception as e:
            logger.error("[DeliverableAutoStaging] Failed to stage deliverable: %s", e)

    # Apply LRU pruning
    _prune_old_staged_artifacts(target_dir, max_keep=MAX_STAGED_ARTIFACTS_LIMIT)

    return staged_results


__all__ = [
    "MAX_STAGED_ARTIFACTS_LIMIT",
    "STAGED_ARTIFACTS_DIR",
    "StagedArtifactMeta",
    "stage_unwritten_deliverables",
]
