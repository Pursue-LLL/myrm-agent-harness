"""
[INPUT]: Subsystem components of verifiable provenance suite
[OUTPUT]: VerifiableProvenanceManager unifying fail-closed guard, residency prover, purge engine, and PII shield
[POS]: myrm_agent_harness.toolkits.memory.verifiable_provenance.manager
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from .fail_closed_guard import FailClosedMemoryGuard
from .models import (
    DestructionReceipt,
    PhysicalResidencyProof,
    PiiShieldDetection,
    TenantSandboxContext,
)
from .physical_purge_engine import PhysicalPurgeDestructionEngine
from .physical_residency_prover import PhysicalStorageResidencyProver
from .pre_ingest_pii_shield import PreIngestPiiShield


class VerifiableProvenanceManager:
    """Unified coordinator for memory physical residency proof, fail-closed guard, purge, and PII shield."""

    def __init__(
        self,
        volume_root_boundary: Path,
        master_environment_secret: str,
        overwrite_passes: int = 3,
    ) -> None:
        self._guard = FailClosedMemoryGuard(master_environment_secret)
        self._prover = PhysicalStorageResidencyProver(volume_root_boundary)
        self._purge_engine = PhysicalPurgeDestructionEngine(overwrite_passes)
        self._pii_shield = PreIngestPiiShield()

    @property
    def guard(self) -> FailClosedMemoryGuard:
        return self._guard

    @property
    def prover(self) -> PhysicalStorageResidencyProver:
        return self._prover

    @property
    def purge_engine(self) -> PhysicalPurgeDestructionEngine:
        return self._purge_engine

    @property
    def pii_shield(self) -> PreIngestPiiShield:
        return self._pii_shield

    def verify_and_prove_residency(
        self,
        file_path: Path,
        context: Optional[TenantSandboxContext],
        extra_metadata: Dict[str, str] | None = None,
    ) -> PhysicalResidencyProof:
        """Validate context under fail-closed contract, then generate physical residency proof."""
        self._guard.validate_request_context(context, file_path)
        assert context is not None  # Guaranteed by validate_request_context
        return self._prover.generate_residency_proof(file_path, context, extra_metadata)

    def verify_and_purge_storage(
        self,
        file_path: Path,
        context: Optional[TenantSandboxContext],
    ) -> DestructionReceipt:
        """Validate context under fail-closed contract, then execute multi-pass physical purge."""
        self._guard.validate_request_context(context, file_path)
        assert context is not None  # Guaranteed by validate_request_context
        return self._purge_engine.purge_storage_file(file_path, context)

    def inspect_memory_content(self, text: str) -> PiiShieldDetection:
        """Inspect and sanitize text prior to persistence to ensure zero sensitive PII leakage."""
        return self._pii_shield.inspect_and_mask(text)
