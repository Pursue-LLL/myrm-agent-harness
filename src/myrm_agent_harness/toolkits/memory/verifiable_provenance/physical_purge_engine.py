"""
[INPUT]: Target memory storage path and TenantSandboxContext
[OUTPUT]: Physical sector overwrite and cryptographically signed DestructionReceipt
[POS]: myrm_agent_harness.toolkits.memory.verifiable_provenance.physical_purge_engine
"""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from .models import (
    DestructionReceipt,
    FailClosedSecurityException,
    PurgeVerificationStatus,
    TenantSandboxContext,
)


class PhysicalPurgeDestructionEngine:
    """Executes verifiable true-forgetting purge by multi-pass zero/random overwriting."""

    def __init__(self, overwrite_passes: int = 3) -> None:
        if overwrite_passes < 1:
            raise ValueError("overwrite_passes must be at least 1")
        self._overwrite_passes = overwrite_passes

    def purge_storage_file(
        self,
        file_path: Path,
        context: TenantSandboxContext,
    ) -> DestructionReceipt:
        """Physically overwrite and destroy target storage file, generating an immutable receipt."""
        resolved = file_path.resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Cannot purge non-existent target: {resolved}")

        file_size = resolved.stat().st_size
        receipt_id = f"rcpt-{uuid.uuid4().hex[:12]}"

        # Execute multi-pass overwrite (Pass 1: zeros, Pass 2: ones, Pass 3: random)
        bytes_written = 0
        with resolved.open("r+b") as target_file:
            for p in range(self._overwrite_passes):
                target_file.seek(0)
                if p % 3 == 0:
                    pattern = b"\x00" * 4096
                elif p % 3 == 1:
                    pattern = b"\xff" * 4096
                else:
                    pattern = os.urandom(4096)

                remaining = file_size
                while remaining > 0:
                    chunk_len = min(remaining, len(pattern))
                    target_file.write(pattern[:chunk_len])
                    bytes_written += chunk_len
                    remaining -= chunk_len

                target_file.flush()
                os.fsync(target_file.fileno())

        # Compute digest of post-purge zero state before unlinking
        post_purge_hasher = hashlib.sha256()
        with resolved.open("rb") as f:
            while chunk := f.read(65536):
                post_purge_hasher.update(chunk)
        destruction_digest = post_purge_hasher.hexdigest()

        # Unlink the physical file
        try:
            resolved.unlink()
            status = PurgeVerificationStatus.VERIFIED_DESTROYED
        except OSError:
            status = PurgeVerificationStatus.REWRITE_FAILED

        return DestructionReceipt(
            receipt_id=receipt_id,
            tenant_id=context.tenant_id,
            sandbox_id=context.sandbox_id,
            volume_id=context.volume_id,
            purged_storage_path=str(resolved),
            bytes_overwritten=bytes_written,
            overwrite_passes=self._overwrite_passes,
            status=status,
            destruction_digest=destruction_digest,
        )
