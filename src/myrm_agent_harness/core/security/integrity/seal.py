"""Persistence integrity and sealing verification domain.

[INPUT]
- hashlib.blake2b (POS: Cryptographic content hashing)
- json (POS: Manifest serialization/deserialization)
- pathlib.Path (POS: Local file reading)

[OUTPUT]
- SealManifest: Immutable dataclass capturing manifest metadata, files, checksums, and sealing state
- IntegritySealer: Pure-domain sealing & checksum verification engine for persistence operations
- IntegrityVerificationResult: Result object containing verification status, corrupted files, and reason

[POS]
Harness core security module for snapshot and persistence write integrity.
Pure domain logic, strictly fail-closed, zero coupling to cloud/multi-tenant platforms.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SEAL_MAGIC_HEADER: str = "MYRM_SEAL_V1"
SEAL_FILENAME: str = ".seal.json"


class IntegrityStatus(StrEnum):
    """Integrity verification status enum."""

    VALID = "valid"
    CORRUPTED = "corrupted"
    UNSEALED = "unsealed"
    MISSING_MANIFEST = "missing_manifest"
    INVALID_SCHEMA = "invalid_schema"


@dataclass(frozen=True)
class FileChecksum:
    """File checksum metadata."""

    rel_path: str
    size_bytes: int
    blake2b_256: str


@dataclass(frozen=True)
class SealManifest:
    """Structured persistence seal manifest."""

    magic: str
    version: int
    session_id: str
    sealed: bool
    created_at_epoch_ms: int
    files: list[FileChecksum]
    total_bytes: int
    manifest_signature: str = ""

    def to_json(self) -> str:
        """Serialize manifest to deterministic formatted JSON."""
        data = asdict(self)
        return json.dumps(data, indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, json_str: str) -> SealManifest | None:
        """Deserialize and validate manifest schema."""
        try:
            data: dict[str, Any] = json.loads(json_str)
            if data.get("magic") != SEAL_MAGIC_HEADER:
                return None
            files_raw = data.get("files", [])
            files: list[FileChecksum] = [
                FileChecksum(
                    rel_path=f["rel_path"],
                    size_bytes=int(f["size_bytes"]),
                    blake2b_256=f["blake2b_256"],
                )
                for f in files_raw
                if "rel_path" in f and "size_bytes" in f and "blake2b_256" in f
            ]
            return cls(
                magic=str(data["magic"]),
                version=int(data.get("version", 1)),
                session_id=str(data.get("session_id", "")),
                sealed=bool(data.get("sealed", False)),
                created_at_epoch_ms=int(data.get("created_at_epoch_ms", 0)),
                files=files,
                total_bytes=int(data.get("total_bytes", 0)),
                manifest_signature=str(data.get("manifest_signature", "")),
            )
        except Exception as e:
            logger.warning("Failed to parse seal manifest: %s", e)
            return None


@dataclass(frozen=True)
class IntegrityVerificationResult:
    """Result of verifying persistence integrity against a manifest."""

    status: IntegrityStatus
    manifest: SealManifest | None = None
    corrupted_files: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def is_valid(self) -> bool:
        return self.status == IntegrityStatus.VALID


class IntegritySealer:
    """Pure domain sealing and integrity verification engine."""

    @staticmethod
    def compute_bytes_checksum(data: bytes) -> str:
        """Compute Blake2b-256 digest of bytes."""
        hasher = hashlib.blake2b(digest_size=32)
        hasher.update(data)
        return hasher.hexdigest()

    @classmethod
    def compute_file_checksum(cls, file_path: str | Path) -> FileChecksum | None:
        """Compute Blake2b-256 digest and size of a local file."""
        p = Path(file_path)
        if not p.is_file():
            return None
        content = p.read_bytes()
        digest = cls.compute_bytes_checksum(content)
        return FileChecksum(
            rel_path=p.name,
            size_bytes=len(content),
            blake2b_256=digest,
        )

    @classmethod
    def create_seal_manifest(
        self,
        session_id: str,
        files_data: dict[str, bytes],
        epoch_ms: int | None = None,
    ) -> SealManifest:
        """Generate a sealed manifest from a dict of relative paths to byte contents."""
        import time

        now_ms = epoch_ms if epoch_ms is not None else int(time.time() * 1000)
        file_checksums: list[FileChecksum] = []
        total_bytes = 0

        for rel_path in sorted(files_data.keys()):
            raw = files_data[rel_path]
            digest = self.compute_bytes_checksum(raw)
            size = len(raw)
            total_bytes += size
            file_checksums.append(
                FileChecksum(
                    rel_path=rel_path,
                    size_bytes=size,
                    blake2b_256=digest,
                )
            )

        # Signature over the file checksum sequence to ensure manifest tamper resistance
        manifest_hasher = hashlib.blake2b(digest_size=32)
        for fc in file_checksums:
            manifest_hasher.update(f"{fc.rel_path}:{fc.size_bytes}:{fc.blake2b_256}\n".encode())
        signature = manifest_hasher.hexdigest()

        return SealManifest(
            magic=SEAL_MAGIC_HEADER,
            version=1,
            session_id=session_id,
            sealed=True,
            created_at_epoch_ms=now_ms,
            files=file_checksums,
            total_bytes=total_bytes,
            manifest_signature=signature,
        )

    @classmethod
    def verify_manifest_and_files(
        self,
        manifest_json: str,
        files_data: dict[str, bytes],
    ) -> IntegrityVerificationResult:
        """Verify the integrity of files against a serialized manifest."""
        manifest = SealManifest.from_json(manifest_json)
        if manifest is None:
            return IntegrityVerificationResult(
                status=IntegrityStatus.INVALID_SCHEMA,
                reason="Failed to deserialize manifest or magic header mismatch",
            )

        if not manifest.sealed:
            return IntegrityVerificationResult(
                status=IntegrityStatus.UNSEALED,
                manifest=manifest,
                reason="Manifest marked unsealed (persistence write was incomplete)",
            )

        # Verify signature
        manifest_hasher = hashlib.blake2b(digest_size=32)
        for fc in manifest.files:
            manifest_hasher.update(f"{fc.rel_path}:{fc.size_bytes}:{fc.blake2b_256}\n".encode())
        expected_sig = manifest_hasher.hexdigest()
        if manifest.manifest_signature and manifest.manifest_signature != expected_sig:
            return IntegrityVerificationResult(
                status=IntegrityStatus.CORRUPTED,
                manifest=manifest,
                reason="Manifest signature mismatch (metadata tampered or corrupted)",
            )

        missing: list[str] = []
        corrupted: list[str] = []

        for expected_fc in manifest.files:
            rel = expected_fc.rel_path
            if rel not in files_data:
                missing.append(rel)
                continue
            actual_bytes = files_data[rel]
            if len(actual_bytes) != expected_fc.size_bytes:
                corrupted.append(rel)
                continue
            actual_digest = self.compute_bytes_checksum(actual_bytes)
            if actual_digest != expected_fc.blake2b_256:
                corrupted.append(rel)

        if missing or corrupted:
            return IntegrityVerificationResult(
                status=IntegrityStatus.CORRUPTED,
                manifest=manifest,
                missing_files=missing,
                corrupted_files=corrupted,
                reason=f"Integrity check failed: {len(missing)} missing, {len(corrupted)} corrupted",
            )

        return IntegrityVerificationResult(
            status=IntegrityStatus.VALID,
            manifest=manifest,
        )
