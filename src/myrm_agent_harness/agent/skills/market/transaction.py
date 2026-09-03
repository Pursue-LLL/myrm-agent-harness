"""Skill installation transaction and snapshot rollback manager.

[INPUT]
- backends.skills.market_protocols::SkillInstallReceipt, SkillFileDigest (POS: Typed receipt model)
- backends.skills.scanning.package_audit::check_lifecycle_scripts (POS: In-memory lifecycle script gate)

[OUTPUT]
- SkillInstallTransaction: Context manager coordinating atomic directory replacement, backup snapshots, and automatic rollback on failure.
- build_skill_receipt(): Helper to compute SHA256 digests and build immutable SkillInstallReceipt.
- write_receipt_file(): Persist receipt.json into installed skill directory.
- read_receipt_file(): Read and parse receipt.json from installed skill directory.

[POS]
Harness-level transaction orchestrator ensuring zero-corrupted half-installs across single/multi-skill packages.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from myrm_agent_harness.backends.skills.market_protocols import (
    SkillFileDigest,
    SkillInstallReceipt,
)

logger = logging.getLogger(__name__)

RECEIPT_FILENAME = "receipt.json"


def compute_files_digest(
    files: dict[str, bytes],
) -> tuple[tuple[SkillFileDigest, ...], str]:
    """Compute individual file SHA256 digests and an overall package manifest hash."""
    digests: list[SkillFileDigest] = []
    hasher = hashlib.sha256()

    for rel_path in sorted(files.keys()):
        content = files[rel_path]
        file_sha = hashlib.sha256(content).hexdigest()
        size_bytes = len(content)
        digests.append(
            SkillFileDigest(
                relative_path=rel_path,
                sha256=file_sha,
                size_bytes=size_bytes,
            )
        )
        hasher.update(f"{rel_path}:{file_sha}\n".encode())

    return tuple(digests), hasher.hexdigest()


def build_skill_receipt(
    *,
    skill_id: str,
    skill_name: str,
    source: str,
    installed_path: str,
    files: dict[str, bytes],
    version: str = "",
    installed_skills: Sequence[str] = (),
    declared_mcp_servers: Sequence[str] = (),
    scan_score: int = 100,
    security_verified: bool = True,
) -> SkillInstallReceipt:
    """Build an immutable SkillInstallReceipt instance from installed file contents."""
    file_digests, manifest_hash = compute_files_digest(files)
    receipt_id = f"rcpt_{hashlib.sha256(f'{skill_id}:{manifest_hash}'.encode()).hexdigest()[:16]}"

    return SkillInstallReceipt(
        receipt_id=receipt_id,
        skill_id=skill_id,
        skill_name=skill_name,
        source=source,
        installed_at=datetime.now(UTC).isoformat(),
        version=version,
        installed_path=installed_path,
        files=file_digests,
        installed_skills=tuple(installed_skills) if installed_skills else (skill_name,),
        declared_mcp_servers=tuple(declared_mcp_servers),
        scan_score=scan_score,
        security_verified=security_verified,
        manifest_hash=manifest_hash,
    )


def write_receipt_file(skill_dir: Path, receipt: SkillInstallReceipt) -> None:
    """Persist receipt.json to skill directory for forensic validation and clean uninstall."""
    receipt_dict = {
        "receipt_id": receipt.receipt_id,
        "skill_id": receipt.skill_id,
        "skill_name": receipt.skill_name,
        "source": receipt.source,
        "installed_at": receipt.installed_at,
        "version": receipt.version,
        "installed_path": receipt.installed_path,
        "files": [
            {
                "relative_path": f.relative_path,
                "sha256": f.sha256,
                "size_bytes": f.size_bytes,
            }
            for f in receipt.files
        ],
        "installed_skills": list(receipt.installed_skills),
        "declared_mcp_servers": list(receipt.declared_mcp_servers),
        "scan_score": receipt.scan_score,
        "security_verified": receipt.security_verified,
        "manifest_hash": receipt.manifest_hash,
    }
    try:
        (skill_dir / RECEIPT_FILENAME).write_text(
            json.dumps(receipt_dict, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        logger.warning("Failed to write receipt.json in %s: %s", skill_dir, exc)


def read_receipt_file(skill_dir: Path) -> SkillInstallReceipt | None:
    """Read receipt.json from skill directory. Returns None if missing or corrupted."""
    receipt_path = skill_dir / RECEIPT_FILENAME
    if not receipt_path.exists():
        return None
    try:
        data = json.loads(receipt_path.read_text(encoding="utf-8"))
        files = tuple(
            SkillFileDigest(
                relative_path=f["relative_path"],
                sha256=f["sha256"],
                size_bytes=int(f["size_bytes"]),
            )
            for f in data.get("files", [])
        )
        return SkillInstallReceipt(
            receipt_id=data.get("receipt_id", ""),
            skill_id=data.get("skill_id", ""),
            skill_name=data.get("skill_name", ""),
            source=data.get("source", ""),
            installed_at=data.get("installed_at", ""),
            version=data.get("version", ""),
            installed_path=data.get("installed_path", str(skill_dir)),
            files=files,
            installed_skills=tuple(data.get("installed_skills", [])),
            declared_mcp_servers=tuple(data.get("declared_mcp_servers", [])),
            scan_score=int(data.get("scan_score", 100)),
            security_verified=bool(data.get("security_verified", True)),
            manifest_hash=data.get("manifest_hash", ""),
        )
    except Exception as exc:
        logger.debug("Failed to read receipt from %s: %s", receipt_path, exc)
        return None


class SkillInstallTransaction:
    """Atomic multi-target installation transaction manager with automatic snapshot rollback."""

    def __init__(self) -> None:
        self._staged_targets: list[tuple[Path, Path | None]] = (
            []
        )  # (target_dir, backup_temp_dir)
        self._created_dirs: list[Path] = []
        self._is_committed = False

    def stage_replace(self, source_dir: Path, target_dir: Path) -> None:
        """Stage an atomic directory replacement by taking a snapshot backup of existing target."""
        target_dir = target_dir.resolve()
        source_dir = source_dir.resolve()

        backup_temp: Path | None = None
        if target_dir.exists():
            backup_temp = Path(
                tempfile.mkdtemp(prefix=f"skill-snap-backup-{target_dir.name}-")
            )
            # Copy current contents to snapshot backup temp
            shutil.copytree(target_dir, backup_temp / "snapshot", dirs_exist_ok=True)
            shutil.rmtree(target_dir)
        else:
            self._created_dirs.append(target_dir)

        target_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_dir, target_dir)
        self._staged_targets.append((target_dir, backup_temp))

    def commit(self) -> None:
        """Commit the transaction and cleanup snapshot backups."""
        self._is_committed = True
        for _, backup_temp in self._staged_targets:
            if backup_temp and backup_temp.exists():
                shutil.rmtree(backup_temp, ignore_errors=True)
        self._staged_targets.clear()
        self._created_dirs.clear()

    def rollback(self) -> None:
        """Rollback all staged targets to their pre-transaction snapshot state."""
        if self._is_committed:
            return

        for target_dir, backup_temp in reversed(self._staged_targets):
            try:
                if target_dir.exists():
                    shutil.rmtree(target_dir, ignore_errors=True)
                if backup_temp and (backup_temp / "snapshot").exists():
                    target_dir.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(backup_temp / "snapshot", target_dir)
            except Exception as exc:
                logger.error(
                    "Error during transaction rollback on %s: %s", target_dir, exc
                )
            finally:
                if backup_temp and backup_temp.exists():
                    shutil.rmtree(backup_temp, ignore_errors=True)

        for created_dir in self._created_dirs:
            if created_dir.exists():
                shutil.rmtree(created_dir, ignore_errors=True)

        self._staged_targets.clear()
        self._created_dirs.clear()

    def __enter__(self) -> SkillInstallTransaction:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        if exc_type is not None:
            logger.warning(
                "Exception detected in SkillInstallTransaction (%s), rolling back...",
                exc_val,
            )
            self.rollback()
        elif not self._is_committed:
            self.commit()
