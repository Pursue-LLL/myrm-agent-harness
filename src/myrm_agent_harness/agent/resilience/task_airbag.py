"""Unattended autonomous run Git safety airbag and time-travel rollback suite.

Provides atomic, zero-copy safety baselines for long-running / unattended agent tasks,
supporting dual-track fallback (Git stash shadow commits or ShadowGit bare repo),
user draft protection, and crash-resilient rollback.

[INPUT]
- agent.file_snapshot::create_file_snapshot_store (POS: 工作区文件快照存储工厂)
- toolkits.code_execution.security.workspace_snapshot::create_workspace_snapshot (POS: Git 零拷贝快照与重置树还原器)
- toolkits.code_execution.security.workspace_snapshot::rollback_workspace_snapshot (POS: Git 零拷贝快照与重置树还原器)
- toolkits.code_execution.security.workspace_snapshot::is_git_repo (POS: Git 仓库探测器)

[OUTPUT]
- TaskAirbagStatus: Enum representing airbag lifecycle state (ARMED, DISMISSED, ROLLED_BACK).
- TaskAirbagManifest: Frozen dataclass capturing the pre-flight baseline.
- TaskAirbagDiffSummary: Summary of files mutated since airbag baseline.
- arm_task_airbag: Capture pre-flight baseline before unattended execution.
- rollback_task_airbag: Atomically restore working tree to pre-flight baseline.
- rollback_task_airbag_with_rescue: Atomically restore working tree, capturing a pre-rollback rescue snapshot.
- get_task_airbag_diff: Inspect cumulative mutations since baseline.

[POS]
Agent-layer unattended task safety net and time-travel undo. The airbag orchestrates the
agent-owned ``file_snapshot`` store with the toolkit Git snapshot utilities, so it is a
runtime binding rather than a framework-agnostic toolkit capability.
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from myrm_agent_harness.agent.file_snapshot import create_file_snapshot_store
from myrm_agent_harness.agent.file_snapshot.types import SnapshotTrigger
from myrm_agent_harness.toolkits.code_execution.security.workspace_snapshot import (
    create_workspace_snapshot,
    is_git_repo,
    rollback_workspace_snapshot,
)

logger = logging.getLogger(__name__)


class TaskAirbagStatus(StrEnum):
    """Lifecycle state of an unattended task safety airbag."""

    ARMED = "armed"
    DISMISSED = "dismissed"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True, slots=True)
class TaskAirbagManifest:
    """Pre-flight baseline snapshot manifest for an unattended task."""

    task_id: str
    workspace_path: str
    base_snapshot_id: str
    is_git_repo: bool
    created_at_epoch_ms: int
    status: TaskAirbagStatus = TaskAirbagStatus.ARMED
    external_effects: tuple[str, ...] = field(default_factory=tuple)
    rescue_snapshot_id: str | None = None

    def with_status(
        self,
        new_status: TaskAirbagStatus,
        rescue_snapshot_id: str | None = None,
    ) -> TaskAirbagManifest:
        return TaskAirbagManifest(
            task_id=self.task_id,
            workspace_path=self.workspace_path,
            base_snapshot_id=self.base_snapshot_id,
            is_git_repo=self.is_git_repo,
            created_at_epoch_ms=self.created_at_epoch_ms,
            status=new_status,
            external_effects=self.external_effects,
            rescue_snapshot_id=rescue_snapshot_id if rescue_snapshot_id is not None else self.rescue_snapshot_id,
        )

    def with_external_effects(self, effects: list[str] | tuple[str, ...]) -> TaskAirbagManifest:
        return TaskAirbagManifest(
            task_id=self.task_id,
            workspace_path=self.workspace_path,
            base_snapshot_id=self.base_snapshot_id,
            is_git_repo=self.is_git_repo,
            created_at_epoch_ms=self.created_at_epoch_ms,
            status=self.status,
            external_effects=tuple(effects),
            rescue_snapshot_id=self.rescue_snapshot_id,
        )


@dataclass(frozen=True, slots=True)
class TaskAirbagDiffSummary:
    """Cumulative changes observed since task airbag was armed."""

    task_id: str
    total_files_changed: int
    modified_files: list[str]
    added_files: list[str]
    deleted_files: list[str]
    external_effects: list[str]
    can_rollback: bool


async def arm_task_airbag(task_id: str, workspace_path: Path | str) -> TaskAirbagManifest | None:
    """Arm safety airbag by capturing an atomic baseline before task execution begins."""
    wpath = Path(workspace_path).resolve()
    if not wpath.exists() or not wpath.is_dir():
        logger.warning("Cannot arm airbag: workspace path invalid: %s", wpath)
        return None

    now_epoch_ms = int(time.time() * 1000)

    # 1. Preferred Track: Native Git Repository (Zero-copy shadow commit, <15ms)
    if is_git_repo(wpath):
        res = create_workspace_snapshot(wpath)
        if res.success and res.snapshot_id:
            logger.info("Armed Git safety airbag for task '%s': snapshot=%s", task_id, res.snapshot_id)
            return TaskAirbagManifest(
                task_id=task_id,
                workspace_path=str(wpath),
                base_snapshot_id=res.snapshot_id,
                is_git_repo=True,
                created_at_epoch_ms=now_epoch_ms,
                status=TaskAirbagStatus.ARMED,
            )

    # 2. Dual-Track Fallback: Non-Git directory handled by ShadowGit / LocalFile store
    try:
        store = await create_file_snapshot_store()
        snap_id = await store.take_snapshot(
            working_dir=str(wpath),
            trigger=SnapshotTrigger.MANUAL,
            description=f"airbag_task_{task_id}",
        )
        if snap_id:
            logger.info(
                "Armed fallback safety airbag for task '%s': snapshot=%s",
                task_id,
                snap_id,
            )
            return TaskAirbagManifest(
                task_id=task_id,
                workspace_path=str(wpath),
                base_snapshot_id=snap_id,
                is_git_repo=False,
                created_at_epoch_ms=now_epoch_ms,
                status=TaskAirbagStatus.ARMED,
            )
    except Exception as exc:
        logger.error("Failed to arm fallback airbag for task '%s': %s", task_id, exc)

    return None


async def rollback_task_airbag_with_rescue(manifest: TaskAirbagManifest) -> tuple[bool, str | None]:
    """Atomically restore working tree to baseline, capturing a pre-rollback rescue snapshot."""
    if manifest.status == TaskAirbagStatus.ROLLED_BACK:
        logger.warning("Airbag for task '%s' already rolled back", manifest.task_id)
        return True, manifest.rescue_snapshot_id

    wpath = Path(manifest.workspace_path).resolve()
    if not wpath.exists():
        logger.error("Cannot rollback: workspace path does not exist: %s", wpath)
        return False, None

    rescue_snapshot_id: str | None = None

    # Step 1: Capture pre-rollback rescue snapshot (12ms zero-copy safety net)
    if manifest.is_git_repo:
        rescue_res = create_workspace_snapshot(wpath)
        if rescue_res.success and rescue_res.snapshot_id:
            rescue_snapshot_id = rescue_res.snapshot_id
            logger.info(
                "Captured Git pre-rollback rescue snapshot '%s' for task '%s'", rescue_snapshot_id, manifest.task_id
            )
    else:
        try:
            store = await create_file_snapshot_store()
            rescue_snapshot_id = await store.take_snapshot(
                working_dir=str(wpath),
                trigger=SnapshotTrigger.MANUAL,
                description=f"airbag_rescue_{manifest.task_id}",
            )
            if rescue_snapshot_id:
                logger.info(
                    "Captured fallback pre-rollback rescue snapshot '%s' for task '%s'",
                    rescue_snapshot_id,
                    manifest.task_id,
                )
        except Exception as exc:
            logger.warning("Failed to capture fallback rescue snapshot for task '%s': %s", manifest.task_id, exc)

    # Step 2: Atomic rollback to pre-flight baseline
    if manifest.is_git_repo:
        success = rollback_workspace_snapshot(wpath, manifest.base_snapshot_id)
        if success:
            logger.info("Successfully rolled back Git airbag for task '%s'", manifest.task_id)
            return True, rescue_snapshot_id
        logger.error("Git rollback failed for task '%s'", manifest.task_id)
        return False, rescue_snapshot_id

    # Non-Git fallback restore via FileSnapshotStore
    try:
        store = await create_file_snapshot_store()
        restore_res = await store.restore(manifest.base_snapshot_id)
        if restore_res.success:
            logger.info("Successfully rolled back fallback airbag for task '%s'", manifest.task_id)
            return True, rescue_snapshot_id
        logger.error("Fallback rollback failed for task '%s': %s", manifest.task_id, restore_res.error)
        return False, rescue_snapshot_id
    except Exception as exc:
        logger.error("Exception during airbag rollback for task '%s': %s", manifest.task_id, exc)
        return False, rescue_snapshot_id


async def rollback_task_airbag(manifest: TaskAirbagManifest) -> bool:
    """Atomically restore working tree to the captured pre-flight baseline."""
    success, _ = await rollback_task_airbag_with_rescue(manifest)
    return success


async def get_task_airbag_diff(manifest: TaskAirbagManifest) -> TaskAirbagDiffSummary:
    """Inspect cumulative file changes and external effects since baseline was captured."""
    wpath = Path(manifest.workspace_path).resolve()
    effects = list(manifest.external_effects)

    if not wpath.exists():
        return TaskAirbagDiffSummary(
            task_id=manifest.task_id,
            total_files_changed=0,
            modified_files=[],
            added_files=[],
            deleted_files=[],
            external_effects=effects,
            can_rollback=False,
        )

    if manifest.is_git_repo and is_git_repo(wpath):
        try:
            # Query git diff status between baseline commit and current working tree
            diff_res = subprocess.run(
                ["git", "diff", "--name-status", manifest.base_snapshot_id],
                cwd=str(wpath),
                capture_output=True,
                text=True,
                timeout=4.0,
                check=False,
            )
            modified: list[str] = []
            added: list[str] = []
            deleted: list[str] = []

            if diff_res.returncode == 0:
                for line in diff_res.stdout.splitlines():
                    parts = line.strip().split(maxsplit=1)
                    if len(parts) == 2:
                        status_code, filename = parts[0], parts[1]
                        if status_code.startswith("M"):
                            modified.append(filename)
                        elif status_code.startswith("A"):
                            added.append(filename)
                        elif status_code.startswith("D"):
                            deleted.append(filename)

            # Untracked new files
            untracked_res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(wpath),
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            if untracked_res.returncode == 0:
                for line in untracked_res.stdout.splitlines():
                    if line.startswith("?? "):
                        f = line[3:].strip()
                        if f not in added:
                            added.append(f)

            total = len(modified) + len(added) + len(deleted)
            return TaskAirbagDiffSummary(
                task_id=manifest.task_id,
                total_files_changed=total,
                modified_files=modified,
                added_files=added,
                deleted_files=deleted,
                external_effects=effects,
                can_rollback=True,
            )
        except Exception as exc:
            logger.warning("Failed to calculate Git airbag diff: %s", exc)

    # Fallback diff calculation via FileSnapshotStore
    try:
        store = await create_file_snapshot_store()
        diff_info = await store.diff(manifest.base_snapshot_id)
        if diff_info:
            modified = [c.path for c in diff_info.changes if str(c.change_type) == "modified"]
            added = [c.path for c in diff_info.changes if str(c.change_type) == "created"]
            deleted = [c.path for c in diff_info.changes if str(c.change_type) == "deleted"]
            return TaskAirbagDiffSummary(
                task_id=manifest.task_id,
                total_files_changed=diff_info.total_changes,
                modified_files=modified,
                added_files=added,
                deleted_files=deleted,
                external_effects=effects,
                can_rollback=True,
            )
    except Exception as exc:
        logger.warning("Failed to calculate fallback airbag diff: %s", exc)

    return TaskAirbagDiffSummary(
        task_id=manifest.task_id,
        total_files_changed=0,
        modified_files=[],
        added_files=[],
        deleted_files=[],
        external_effects=effects,
        can_rollback=manifest.status != TaskAirbagStatus.ROLLED_BACK,
    )
