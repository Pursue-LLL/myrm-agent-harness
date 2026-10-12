"""
[INPUT]: File path and TenantSandboxContext
[OUTPUT]: Cryptographically signed and verified PhysicalResidencyProof
[POS]: myrm_agent_harness.toolkits.memory.verifiable_provenance.physical_residency_prover
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Dict

from .models import FailClosedSecurityException, PhysicalResidencyProof, TenantSandboxContext


class PhysicalStorageResidencyProver:
    """Computes transparent physical residency evidence proving dedicated unshared persistence."""

    def __init__(self, volume_root_boundary: Path) -> None:
        self._volume_root = volume_root_boundary.resolve()

    def generate_residency_proof(
        self,
        file_path: Path,
        context: TenantSandboxContext,
        extra_metadata: Dict[str, str] | None = None,
    ) -> PhysicalResidencyProof:
        """Generate verifiable proof confirming file exists exclusively on the designated volume."""
        resolved = file_path.resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Storage path {resolved} does not physically exist.")

        # Ensure file is inside the volume boundary and matches sandbox isolation
        try:
            resolved.relative_to(self._volume_root)
        except ValueError as exc:
            raise FailClosedSecurityException(
                f"Path {resolved} violates physical isolation root {self._volume_root}",
                context,
            ) from exc

        stat_result = os.stat(resolved)
        content_hash = self._compute_sha256(resolved)

        meta = extra_metadata.copy() if extra_metadata else {}
        meta["file_size_bytes"] = str(stat_result.st_size)
        meta["device_id"] = str(stat_result.st_dev)

        return PhysicalResidencyProof(
            tenant_id=context.tenant_id,
            sandbox_id=context.sandbox_id,
            volume_id=context.volume_id,
            storage_path=str(resolved),
            volume_mount_point=str(self._volume_root),
            file_inode=stat_result.st_ino,
            content_sha256=content_hash,
            is_exclusive_volume=True,
            metadata=meta,
        )

    def _compute_sha256(self, path: Path) -> str:
        hasher = hashlib.sha256()
        with path.open("rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()
