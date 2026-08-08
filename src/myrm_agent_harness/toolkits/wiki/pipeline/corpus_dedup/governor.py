"""Apply user dispositions to duplicate groups.

[POS]
See module docstring.
"""

from __future__ import annotations

import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

from myrm_agent_harness.toolkits.wiki.core.claims_contract import sha256_raw_file
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.cognitive_map.events import (
    WikiMapEvent,
    WikiMapEventType,
)
from myrm_agent_harness.toolkits.wiki.pipeline.cognitive_map.writer import (
    append_log_entry,
)
from myrm_agent_harness.toolkits.wiki.pipeline.corpus_dedup.path_utils import (
    normalize_raw_relative_path,
)
from myrm_agent_harness.toolkits.wiki.pipeline.corpus_dedup.store import (
    CorpusDedupStore,
)
from myrm_agent_harness.toolkits.wiki.pipeline.corpus_dedup.types import (
    DedupTier,
    DispositionAction,
    DispositionResult,
    DuplicateGroup,
    ExcludedRawEntry,
    GroupStatus,
    TrashedRawEntry,
    VaultHygieneSnapshot,
)
from myrm_agent_harness.toolkits.wiki.pipeline.raw_gate.evidence_removal import (
    remove_raw_evidence,
)

logger = logging.getLogger(__name__)


class CorpusDedupGovernor:
    """Execute trash/exclude/dismiss/defer actions for duplicate groups."""

    def __init__(self, structure: WikiStructure) -> None:
        self._structure = structure
        self._store = CorpusDedupStore(structure)

    @property
    def store(self) -> CorpusDedupStore:
        return self._store

    def get_corpus_trash_dir(self) -> Path:
        trash_dir = self._structure.base_dir / ".corpus_trash"
        trash_dir.mkdir(parents=True, exist_ok=True)
        return trash_dir

    async def apply_disposition(
        self,
        group_id: int,
        action: DispositionAction,
        *,
        reason: str,
        compiler: object | None = None,
        indexer: object | None = None,
    ) -> DispositionResult:
        group = self._store.get_group(group_id)
        if group is None:
            msg = f"Duplicate group not found: {group_id}"
            raise ValueError(msg)

        if action == DispositionAction.DEFER:
            self._store.update_group_status(group_id, GroupStatus.DEFERRED)
            return DispositionResult(group_id=group_id, action=action)

        if action == DispositionAction.DISMISS:
            paths = [member.relative_path for member in group.members]
            for left_index, left in enumerate(paths):
                for right in paths[left_index + 1 :]:
                    self._store.add_dismissed_pair(left, right)
            self._store.update_group_status(group_id, GroupStatus.RESOLVED)
            return DispositionResult(
                group_id=group_id, action=action, affected_paths=tuple(paths)
            )

        affected: list[str] = []
        prevented = 0
        keep_path = group.recommended_keep_path
        for member in group.members:
            if member.relative_path == keep_path:
                continue
            if action == DispositionAction.EXCLUDE:
                self._store.add_excluded_path(
                    normalize_raw_relative_path(member.relative_path),
                    reason=reason,
                )
                affected.append(member.relative_path)
                prevented += 1
            elif action == DispositionAction.TRASH:
                moved = await self._trash_raw_path(
                    member.relative_path,
                    reason=reason,
                    compiler=compiler,
                    indexer=indexer,
                )
                if moved:
                    affected.append(member.relative_path)
                    prevented += 1

        if prevented:
            self._store.increment_compile_jobs_prevented(prevented)
        self._store.update_group_status(group_id, GroupStatus.RESOLVED)
        return DispositionResult(
            group_id=group_id,
            action=action,
            affected_paths=tuple(affected),
            compile_jobs_prevented=prevented,
        )

    async def _trash_raw_path(
        self,
        relative_path: str,
        *,
        reason: str,
        compiler: object | None,
        indexer: object | None,
    ) -> bool:
        normalized = normalize_raw_relative_path(relative_path)
        raw_path = self._structure.get_raw_file_path(normalized)
        if not raw_path.exists():
            return False
        content_hash = sha256_raw_file(raw_path)
        trash_dir = self.get_corpus_trash_dir()
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        safe_name = relative_path.replace("/", "__")
        trash_name = f"{timestamp}__{safe_name}"
        trash_path = trash_dir / trash_name
        trash_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(raw_path), str(trash_path))
        self._store.add_trashed_path(
            normalized,
            trash_relpath=f".corpus_trash/{trash_name}",
            content_hash=content_hash,
        )
        await remove_raw_evidence(
            self._structure,
            normalized,
            reason=reason,
            caller="settings",
            delete_file=False,
            compiler=compiler,
            indexer=indexer,
        )
        return True

    def list_vault_hygiene(self) -> VaultHygieneSnapshot:
        return self._store.build_vault_hygiene_snapshot()

    async def restore_trashed_raw(
        self,
        relative_path: str,
        *,
        compiler: object | None = None,
    ) -> TrashedRawEntry:
        normalized = normalize_raw_relative_path(relative_path)
        entry = self._store.get_trashed_entry(normalized)
        if entry is None:
            msg = f"Trashed raw file not found: {normalized}"
            raise ValueError(msg)

        trash_path = self._structure.base_dir / entry.trash_relpath
        if not trash_path.is_file():
            msg = f"Corpus trash file missing on disk: {entry.trash_relpath}"
            raise ValueError(msg)

        raw_path = self._structure.get_raw_file_path(normalized)
        if raw_path.exists():
            msg = f"Raw file already exists: {normalized}"
            raise ValueError(msg)

        raw_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(trash_path), str(raw_path))
        if not self._store.remove_trashed_path(normalized):
            logger.warning(
                "Restored raw file on disk but failed to clear trashed_paths entry: %s",
                normalized,
            )
        if compiler is not None:
            enqueue = getattr(compiler, "enqueue_file", None)
            if callable(enqueue):
                enqueue(raw_path)
        try:
            append_log_entry(
                self._structure,
                WikiMapEvent(
                    event_type=WikiMapEventType.EVIDENCE_RESTORED,
                    summary=f"Restored raw evidence {normalized}",
                    details={
                        "path": normalized,
                        "trash_relpath": entry.trash_relpath,
                        "content_hash": entry.content_hash,
                    },
                ),
            )
        except OSError as exc:
            logger.warning(
                "Failed to append restore log entry for %s: %s", normalized, exc
            )
        return entry

    def undo_excluded_raw(self, relative_path: str) -> ExcludedRawEntry:
        normalized = normalize_raw_relative_path(relative_path)
        match = self._store.get_excluded_entry(normalized)
        if match is None:
            msg = f"Excluded raw file not found: {normalized}"
            raise ValueError(msg)
        if not self._store.remove_excluded_path(normalized):
            msg = f"Excluded raw file not found: {normalized}"
            raise ValueError(msg)
        return match

    def blocking_open_groups(self) -> list[DuplicateGroup]:
        groups = self._store.list_groups(status=GroupStatus.OPEN)
        return [
            group
            for group in groups
            if group.tier in {DedupTier.EXACT, DedupTier.NORMALIZED}
        ]
