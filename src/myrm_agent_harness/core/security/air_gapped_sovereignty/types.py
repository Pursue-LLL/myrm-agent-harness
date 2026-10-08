"""
[POS] src/myrm_agent_harness/core/security/air_gapped_sovereignty/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] NetworkConnectivityModeEnum, CryptoAlgorithmSuiteEnum, ModelFallbackTarget, OfflineTrustAnchor, OfflineCertValidationResult, AuditBundleRecord, AirGappedSovereigntyMetrics

Data structures and specifications for Air-Gapped Offline Trust Store & Sovereign Model Fallback Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class NetworkConnectivityModeEnum(StrEnum):
    """Network operational environment mode."""

    ONLINE = "ONLINE"
    AIR_GAPPED_ISOLATED = "AIR_GAPPED_ISOLATED"
    DEGRADED_FAILOVER = "DEGRADED_FAILOVER"


class CryptoAlgorithmSuiteEnum(StrEnum):
    """Cryptographic cipher suite selector."""

    STANDARD_AES_SHA256 = "STANDARD_AES_SHA256"
    SOVEREIGN_GM_SM2_SM3_SM4 = "SOVEREIGN_GM_SM2_SM3_SM4"


@dataclass(frozen=True)
class ModelFallbackTarget:
    """Target endpoint specification for sovereign local or remote models."""

    model_id: str
    endpoint_url: str
    provider: str = "ollama"
    is_local_sovereign: bool = True
    context_window: int = 32768


@dataclass(frozen=True)
class OfflineTrustAnchor:
    """Pre-distributed offline Root Certificate Authority anchor."""

    ca_name: str
    root_cert_pem: str
    valid_until: float
    fingerprint_sm3: str


@dataclass(frozen=True)
class OfflineCertValidationResult:
    """Outcome of offline certificate validity and revocation check."""

    is_valid: bool
    reason: str
    ca_name: str | None = None
    is_revoked: bool = False
    fingerprint_sm3: str | None = None


@dataclass(frozen=True)
class AuditBundleRecord:
    """Sealed air-gapped evidentiary audit archive bundle."""

    bundle_id: str
    timestamp: float
    record_count: int
    sm3_root_digest: str
    is_sealed: bool = True
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class AirGappedSovereigntyMetrics:
    """Cumulative operational metrics for air-gapped and sovereign fallback subsystem."""

    total_offline_validations: int = 0
    valid_certificates_count: int = 0
    crl_revocation_hits: int = 0
    model_fallback_events: int = 0
    audit_bundles_sealed: int = 0
