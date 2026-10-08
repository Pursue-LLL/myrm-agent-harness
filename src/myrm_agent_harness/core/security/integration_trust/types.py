"""Domain types and models for Integration Egress Trust Lifecycle.

[INPUT]
- None.

[OUTPUT]
- Typed dataclasses and enums representing pre-connect disclosure cards,
  purge-on-disconnect receipts, provider revocation configurations, and lifecycle outcomes.

[POS]
- Harness core domain models ensuring integration authorizations provide full transparency,
  atomic memory purification upon disconnection, and verifiable account-level token revocation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DataFlowDirection(StrEnum):
    """Direction of data ingress or egress between agent and integration provider."""

    READ_INGRESS = "READ_INGRESS"
    WRITE_EGRESS = "WRITE_EGRESS"
    BIDIRECTIONAL = "BIDIRECTIONAL"


class RevocationStatus(StrEnum):
    """Result of account-level OAuth token revocation on the external provider."""

    REVOKED_REMOTE = "REVOKED_REMOTE"
    REVOKED_LOCAL_ONLY = "REVOKED_LOCAL_ONLY"
    REVOCATION_FAILED = "REVOCATION_FAILED"
    NOT_SUPPORTED = "NOT_SUPPORTED"


@dataclass(frozen=True)
class PreConnectDisclosure:
    """Pre-connect disclosure card explaining access scope and data lifecycle to user."""

    provider_id: str
    display_name: str
    data_types_read: tuple[str, ...]
    actions_performed: tuple[str, ...]
    storage_locations: tuple[str, ...]
    purge_policy_summary: str
    flow_direction: DataFlowDirection = DataFlowDirection.BIDIRECTIONAL


@dataclass(frozen=True)
class ProviderRevokeConfig:
    """Provider-specific token revocation endpoint and fallback manual URL."""

    provider_id: str
    revocation_endpoint: str | None
    supports_remote_revoke: bool
    manual_revoke_url: str | None = None


@dataclass(frozen=True)
class DisconnectPurgeReceipt:
    """Cryptographic or audit receipt confirming memory tree purge and provider revocation."""

    provider_id: str
    cleared_memory_trees: int
    cleared_documents: int
    revocation_status: RevocationStatus
    revocation_receipt: str | None
    manual_revoke_url: str | None
    timestamp: str


class IntegrationTrustError(Exception):
    """Base exception for integration trust lifecycle operations."""


class ProviderRevocationError(IntegrationTrustError):
    """Raised when remote token revocation fails unexpectedly."""


class PurgeExecutionError(IntegrationTrustError):
    """Raised when memory tree or document cleanup encounters an unrecoverable failure."""
