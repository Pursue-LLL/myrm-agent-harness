"""Type definitions for Verifiable Cryptographic Erasure and Complete Data Portability."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ErasureMethod(StrEnum):
    """Sanitization methods adhering to NIST SP 800-88 and DoD 5220.22-M."""

    CRYPTOGRAPHIC = "CRYPTOGRAPHIC"  # Instant purge of tenant DEK, mathematically rendering data unrecoverable
    OVERWRITE_ZERO = "OVERWRITE_ZERO"  # Single-pass zero-byte fill
    DOD_3PASS = "DOD_3PASS"  # DoD 5220.22-M 3-pass (zeros, ones, pseudo-random)
    CASCADE_ALL = "CASCADE_ALL"  # Cryptographic DEK destruction + multi-pass physical overwrite


@dataclass(slots=True, frozen=True)
class ShreddingPassConfig:
    """Configuration for physical file shredding operations."""

    passes: int = 3
    pattern_mode: str = "DOD"  # DOD, ZERO, or RANDOM
    flush_sync: bool = True


@dataclass(slots=True, frozen=True)
class DeletionCertificate:
    """Verifiable cryptographic certificate proving irreversible deletion."""

    certificate_id: str
    tenant_id: str
    erasure_method: ErasureMethod
    target_resource_types: list[str]
    shredded_bytes: int
    payload_checksum_prior: str
    timestamp: float
    signer_identity: str
    certificate_signature: str


@dataclass(slots=True, frozen=True)
class ErasureResult:
    """Outcome of an erasure or shredding operation."""

    success: bool
    tenant_id: str
    erasure_method: ErasureMethod
    certificate: DeletionCertificate | None
    error_message: str | None = None


@dataclass(slots=True, frozen=True)
class DataPortabilityBundle:
    """GDPR Article 20 compliant data portability container."""

    bundle_id: str
    tenant_id: str
    exported_at: float
    conversations: list[dict[str, str]] = field(default_factory=list)
    memory_entries: list[dict[str, str]] = field(default_factory=list)
    agent_configs: list[dict[str, str]] = field(default_factory=list)
    bundle_sha256: str = ""
    bundle_signature: str = ""
