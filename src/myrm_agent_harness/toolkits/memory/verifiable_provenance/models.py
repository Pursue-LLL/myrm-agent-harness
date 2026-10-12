"""
[INPUT]: None - Pure verifiable provenance & physical isolation domain models
[OUTPUT]: Data classes and domain schemas for memory residency, fail-closed guard, destruction receipt, and PII shield
[POS]: myrm_agent_harness.toolkits.memory.verifiable_provenance.models
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional


class FailClosedAction(str, enum.Enum):
    """Enforcement outcome when tenant or hardware binding contract is breached."""
    HARD_REJECT = "hard_reject"
    RAISE_ALARM = "raise_alarm"
    HALT_TRANSACTION = "halt_transaction"


class PiiCategory(str, enum.Enum):
    """Categories of strictly private information requiring pre-ingest interception."""
    CHILD_IDENTITY = "child_identity"
    PRECISE_RESIDENTIAL_ADDRESS = "precise_residential_address"
    FINANCIAL_INSTRUMENT = "financial_instrument"
    GOVERNMENT_ID = "government_id"


class PurgeVerificationStatus(str, enum.Enum):
    """Verification state of a physical memory purge operation."""
    VERIFIED_DESTROYED = "verified_destroyed"
    STORAGE_UNMOUNTED = "storage_unmounted"
    REWRITE_FAILED = "rewrite_failed"


@dataclass(frozen=True)
class TenantSandboxContext:
    """Authentication and boundary context for memory partition resolution."""
    tenant_id: str
    sandbox_id: str
    volume_id: str
    environment_token: str
    issued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class PhysicalResidencyProof:
    """Verifiable proof that memory physically resides in a dedicated unshared volume."""
    tenant_id: str
    sandbox_id: str
    volume_id: str
    storage_path: str
    volume_mount_point: str
    file_inode: int
    content_sha256: str
    is_exclusive_volume: bool
    verified_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DestructionReceipt:
    """Non-repudiable receipt proving complete physical destruction of memory partition."""
    receipt_id: str
    tenant_id: str
    sandbox_id: str
    volume_id: str
    purged_storage_path: str
    bytes_overwritten: int
    overwrite_passes: int
    status: PurgeVerificationStatus
    destruction_digest: str
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class PiiShieldDetection:
    """Result of PII shield inspection before memory persistence."""
    intercepted: bool
    detected_categories: List[PiiCategory]
    sanitized_text: str
    masked_spans: List[str]
    has_child_privacy_violation: bool


class FailClosedSecurityException(PermissionError):
    """Raised when memory access violates strict zero-fallback tenant isolation."""
    def __init__(self, message: str, context: Optional[TenantSandboxContext] = None) -> None:
        super().__init__(message)
        self.context = context
