"""Skill sync manager — orchestrates bidirectional skill synchronization.

Reuses existing framework infrastructure:
- SkillPacker for transport format (ZIP bundles)
- SkillSyncManifest for incremental state tracking
- ThresholdQualityGate for push validation

[INPUT]
- .protocols::SkillSyncProtocol, SkillQualityGateProtocol
- .manifest::SkillSyncManifest
- .types::GateVerdict, PushResult, PullResult, SyncStatus
- agent.skills.packaging.packer::SkillPacker

[OUTPUT]
- SkillSyncManager: Sync orchestrator

[POS]
Core sync orchestrator for collective skill evolution.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

from myrm_agent_harness.agent.skills.packaging.packer import SkillPacker

from .manifest import SkillSyncManifest
from .protocols import SkillQualityGateProtocol, SkillSyncProtocol
from .quality_gate import ThresholdQualityGate
from .types import GateVerdict, PullResult, PushResult, SyncStatus

logger = logging.getLogger(__name__)

_SKILL_MD_FILE = "SKILL.md"


def _compute_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class SkillSyncManager:
    """Orchestrates bidirectional skill synchronization.

    Coordinates between:
    - SkillSyncProtocol: the actual transport (local FS / HTTP)
    - SkillQualityGateProtocol: push quality validation
    - SkillSyncManifest: incremental state tracking
    - SkillPacker/SkillUnpacker: transport format

    Usage:
        manager = SkillSyncManager(
            sync_backend=local_fs_sync,
            manifest=SkillSyncManifest(db_path),
            workspace_skills_path=Path("~/.myrm/skills"),
        )
        push_result = await manager.push_evolved_skills()
        pull_result = await manager.pull_shared_skills()
    """

    def __init__(
        self,
        sync_backend: SkillSyncProtocol,
        manifest: SkillSyncManifest,
        workspace_skills_path: Path,
        quality_gate: SkillQualityGateProtocol | None = None,
    ) -> None:
        self._backend = sync_backend
        self._manifest = manifest
        self._skills_path = Path(workspace_skills_path).resolve()
        self._gate = quality_gate or ThresholdQualityGate()
        self._packer = SkillPacker()
        self._sync_lock = asyncio.Lock()

    @property
    def is_syncing(self) -> bool:
        return self._sync_lock.locked()

    async def get_status(self) -> SyncStatus:
        """Get current sync status for UI display."""
        pending_push = self._manifest.get_pending_push()
        pending_pull = self._manifest.get_pending_pull()
        last_sync = self._manifest.get_last_sync_time()

        return SyncStatus(
            enabled=True,
            last_sync_at=last_sync,
            pending_push_count=len(pending_push),
            pending_pull_count=len(pending_pull),
            is_syncing=self.is_syncing,
        )

    async def push_evolved_skills(
        self,
        skill_metrics: dict[str, tuple[float, int]] | None = None,
    ) -> PushResult:
        """Push locally evolved skills that pass quality gate.

        Args:
            skill_metrics: Optional {skill_name: (effective_rate, total_executions)}.
                          If not provided, quality gate is skipped (manual push).

        Returns:
            PushResult with per-skill details.
        """
        if self._sync_lock.locked():
            return PushResult(success=False, error="Sync already in progress")

        async with self._sync_lock:
            return await self._do_push(skill_metrics)

    async def _do_push(
        self,
        skill_metrics: dict[str, tuple[float, int]] | None = None,
    ) -> PushResult:
        """Internal push implementation (called under lock)."""
        pending = self._manifest.get_pending_push()
        if not pending:
            logger.info("No skills pending push")
            return PushResult(success=True)

        bundles: dict[str, bytes] = {}
        rejected: list[str] = []
        gate_verdicts: dict[str, GateVerdict] = {}

        for skill_name in pending:
            skill_dir = self._skills_path / skill_name
            skill_md = skill_dir / _SKILL_MD_FILE
            if not skill_md.exists():
                logger.warning("Skill '%s' has no SKILL.md, skipping push", skill_name)
                continue

            content = skill_md.read_text(encoding="utf-8")

            if skill_metrics and skill_name in skill_metrics:
                rate, count = skill_metrics[skill_name]
                verdict = await self._gate.evaluate(
                    skill_name=skill_name,
                    skill_content=content,
                    effective_rate=rate,
                    total_executions=count,
                )
                gate_verdicts[skill_name] = verdict

                if not verdict.passed:
                    rejected.append(skill_name)
                    continue

            file_contents = self._collect_skill_files(skill_dir)
            pack_result = self._packer.package_files(
                skill_name=skill_name,
                version="1.0.0",
                file_contents=file_contents,
            )
            if pack_result.success and pack_result.zip_content:
                bundles[skill_name] = pack_result.zip_content

        if not bundles:
            return PushResult(
                success=True,
                rejected_count=len(rejected),
                rejected_skills=rejected,
                gate_verdicts=gate_verdicts,
            )

        result = await self._backend.push_skills(bundles)

        for skill_name in bundles:
            if skill_name not in (result.rejected_skills or []):
                self._manifest.mark_pushed(skill_name)

        self._manifest.set_last_sync_time()
        return PushResult(
            success=result.success,
            pushed_count=result.pushed_count,
            rejected_count=result.rejected_count + len(rejected),
            rejected_skills=(result.rejected_skills or []) + rejected,
            gate_verdicts=gate_verdicts,
            error=result.error,
        )

    async def pull_shared_skills(self) -> PullResult:
        """Pull updated skills from shared repository.

        Writes new/updated skills to the workspace skills directory.
        Uses manifest for incremental sync — only pulls what changed.
        Automatically updates manifest for pulled skills.

        Returns:
            PullResult with counts of new/updated/conflicting skills.
        """
        if self._sync_lock.locked():
            return PullResult(success=False, error="Sync already in progress")

        async with self._sync_lock:
            return await self._do_pull()

    async def _do_pull(self) -> PullResult:
        """Internal pull implementation (called under lock)."""
        last_sync = self._manifest.get_last_sync_time()
        since = last_sync.isoformat() if last_sync else ""

        result = await self._backend.pull_skills(since_version=since)

        for skill_name in result.pulled_skills:
            self.register_local_skill(skill_name)

        self._manifest.set_last_sync_time()
        return result

    async def full_sync(
        self,
        skill_metrics: dict[str, tuple[float, int]] | None = None,
    ) -> tuple[PushResult, PullResult]:
        """Perform a full bidirectional sync: pull first, then push.

        Pull-first strategy prevents overwriting remote updates
        with stale local versions. Acquires lock once for both operations.
        """
        if self._sync_lock.locked():
            return (
                PushResult(success=False, error="Sync already in progress"),
                PullResult(success=False, error="Sync already in progress"),
            )

        async with self._sync_lock:
            pull_result = await self._do_pull()
            push_result = await self._do_push(skill_metrics)
            return push_result, pull_result

    def register_local_skill(self, skill_name: str) -> None:
        """Register a local skill change in the manifest.

        Called by the evolution system when a skill is created/updated.
        """
        skill_dir = self._skills_path / skill_name
        skill_md = skill_dir / _SKILL_MD_FILE
        if not skill_md.exists():
            return

        content = skill_md.read_bytes()
        sha256 = _compute_sha256(content)
        self._manifest.update_local(skill_name, sha256)

    def _collect_skill_files(self, skill_dir: Path) -> dict[str, bytes | str]:
        """Collect all files in a skill directory for packing."""
        files: dict[str, bytes | str] = {}
        if not skill_dir.is_dir():
            return files

        for file_path in skill_dir.rglob("*"):
            if file_path.is_file():
                rel_path = file_path.relative_to(skill_dir).as_posix()
                try:
                    files[rel_path] = file_path.read_bytes()
                except OSError:
                    logger.warning("Failed to read %s, skipping", file_path)

        return files
