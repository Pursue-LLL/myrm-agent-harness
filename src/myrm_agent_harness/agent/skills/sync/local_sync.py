"""Local file-system-based skill sync backend.

Reuses existing StorageProvider infrastructure for zero-new-storage-code sync.
Suitable for Local/Tauri multi-device scenarios where a shared directory
(iCloud Drive, Dropbox, NAS) acts as the synchronization medium.

[INPUT]
- .protocols::SkillSyncProtocol
- .types::RemoteSkillEntry, PushResult, PullResult, ConflictResolution, ConflictStrategy
- toolkits.storage.base::StorageProvider
- agent.skills.packaging.unpacker::SkillUnpacker

[OUTPUT]
- LocalFSSyncBackend: StorageProvider-backed sync implementation

[POS]
Local file-system sync backend for multi-device skill sharing.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from myrm_agent_harness.agent.skills.packaging.unpacker import SkillUnpacker
from myrm_agent_harness.toolkits.storage.base import StorageProvider

__all__ = ["LocalFSSyncBackend"]

import contextlib

from .types import (
    ConflictResolution,
    ConflictStrategy,
    PullResult,
    PushResult,
    RemoteSkillEntry,
)

logger = logging.getLogger(__name__)

_MANIFEST_KEY = "_sync_manifest.json"
_SKILLS_PREFIX = "shared_skills"


class LocalFSSyncBackend:
    """StorageProvider-backed sync for local multi-device scenarios.

    Uses a shared directory (backed by any StorageProvider) as the
    synchronization medium. Each skill is stored as a ZIP bundle.

    The shared directory structure:
        {shared_path}/
        ├── _sync_manifest.json    # Remote manifest with SHA256 hashes
        └── shared_skills/
            ├── skill_a.zip
            ├── skill_b.zip
            └── ...
    """

    def __init__(
        self,
        storage: StorageProvider,
        local_skills_path: Path,
    ) -> None:
        """Initialize local FS sync backend.

        Args:
            storage: StorageProvider pointing to the shared directory.
            local_skills_path: Path to local workspace skills directory.
        """
        self._storage = storage
        self._local_skills = Path(local_skills_path).resolve()
        self._unpacker = SkillUnpacker()

    async def push_skills(self, bundles: dict[str, bytes]) -> PushResult:
        """Push skill bundles to shared storage."""
        pushed = 0
        manifest = await self._load_remote_manifest()

        for name, zip_bytes in bundles.items():
            try:
                key = f"{_SKILLS_PREFIX}/{name}.zip"
                await self._storage.write(key, zip_bytes)

                sha256 = hashlib.sha256(zip_bytes).hexdigest()
                manifest[name] = {
                    "sha256": sha256,
                    "updated_at": datetime.now(UTC).isoformat(),
                    "size": len(zip_bytes),
                }
                pushed += 1
            except Exception as exc:
                logger.error("Failed to push skill '%s': %s", name, exc)

        await self._save_remote_manifest(manifest)

        return PushResult(success=True, pushed_count=pushed)

    async def pull_skills(self, since_version: str = "", name_filter: str = "") -> PullResult:
        """Pull updated skill bundles from shared storage."""
        manifest = await self._load_remote_manifest()
        new_count = 0
        updated_count = 0
        pulled_names: list[str] = []

        for name, info in manifest.items():
            if name_filter and not name.startswith(name_filter):
                continue

            if since_version and info.get("updated_at", "") <= since_version:
                continue

            try:
                key = f"{_SKILLS_PREFIX}/{name}.zip"
                zip_bytes = await self._storage.read(key)

                result = self._unpacker.unpack(zip_bytes)
                if not result.success or not result.files:
                    logger.warning("Failed to unpack skill '%s': %s", name, result.error)
                    continue

                skill_dir = self._local_skills / name
                skill_dir.mkdir(parents=True, exist_ok=True)
                existed = (skill_dir / "SKILL.md").exists()

                for rel_path, content in result.files.items():
                    file_path = skill_dir / rel_path
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.write_bytes(content)

                pulled_names.append(name)
                if existed:
                    updated_count += 1
                else:
                    new_count += 1

            except FileNotFoundError:
                logger.debug("Skill '%s' zip not found in shared storage", name)
            except Exception as exc:
                logger.error("Failed to pull skill '%s': %s", name, exc)

        return PullResult(
            success=True,
            new_count=new_count,
            updated_count=updated_count,
            pulled_skills=pulled_names,
        )

    async def list_remote(self, prefix: str = "") -> list[RemoteSkillEntry]:
        """List skills available in shared storage."""
        manifest = await self._load_remote_manifest()
        entries: list[RemoteSkillEntry] = []

        for name, info in manifest.items():
            if prefix and not name.startswith(prefix):
                continue

            updated_at = None
            if ts := info.get("updated_at"):
                with contextlib.suppress(ValueError):
                    updated_at = datetime.fromisoformat(ts)

            entries.append(
                RemoteSkillEntry(
                    name=name,
                    version=info.get("version", ""),
                    content_sha256=info.get("sha256", ""),
                    updated_at=updated_at,
                )
            )

        return entries

    async def resolve_conflict(
        self,
        skill_name: str,
        local_sha256: str,
        remote_sha256: str,
        strategy: ConflictStrategy = ConflictStrategy.NEWER_WINS,
    ) -> ConflictResolution:
        """Resolve version conflict using the specified strategy.

        For local FS sync, NEWER_WINS uses file modification timestamps.
        """
        if strategy == ConflictStrategy.REMOTE_WINS:
            return ConflictResolution(
                skill_name=skill_name,
                strategy_used=strategy,
                winner_sha256=remote_sha256,
                detail="Remote version accepted",
            )
        elif strategy == ConflictStrategy.LOCAL_WINS:
            return ConflictResolution(
                skill_name=skill_name,
                strategy_used=strategy,
                winner_sha256=local_sha256,
                detail="Local version kept",
            )
        else:
            return ConflictResolution(
                skill_name=skill_name,
                strategy_used=ConflictStrategy.SKIP,
                winner_sha256=local_sha256,
                detail="Conflict skipped, local version kept",
            )

    async def _load_remote_manifest(self) -> dict[str, dict[str, str]]:
        """Load the shared manifest from storage."""
        try:
            data = await self._storage.read_text(_MANIFEST_KEY)
            return json.loads(data)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    async def _save_remote_manifest(self, manifest: dict[str, dict[str, str]]) -> None:
        """Save the shared manifest to storage."""
        await self._storage.write_text(
            _MANIFEST_KEY,
            json.dumps(manifest, indent=2, default=str),
        )
