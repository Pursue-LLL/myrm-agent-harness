"""Type definitions for Vetted Plugin Registry Trust Chain and Dynamic Capability Attestation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PluginTrustTier(StrEnum):
    """Trust hierarchy for external plugin ecosystem."""

    OFFICIAL_VERIFIED = "OFFICIAL_VERIFIED"  # Official first-party or audited tier with cryptographic endorsement
    VETTED_COMMUNITY = "VETTED_COMMUNITY"  # Community plugin passed through automated vetted CI pipeline
    UNREVIEWED_COMMUNITY = "UNREVIEWED_COMMUNITY"  # Third-party unreviewed plugin requiring explicit user opt-in
    COMPROMISED_REVOKED = "COMPROMISED_REVOKED"  # Known vulnerable or malicious plugin blocked fail-closed


@dataclass(slots=True, frozen=True)
class PluginCapabilityManifest:
    """Declared minimal privilege capabilities declared by a plugin."""

    plugin_id: str
    version: str
    network_domains: list[str] = field(default_factory=list)
    file_access_scope: str = "WORKSPACE_ONLY"
    allow_shell_exec: bool = False
    allowed_env_vars: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class PluginSignaturePackage:
    """Cryptographically signed release package."""

    plugin_id: str
    version: str
    payload_sha256: str
    signature: str
    signer_identity: str
    trust_tier: PluginTrustTier
    signed_at: float


@dataclass(slots=True, frozen=True)
class CapabilityAttestationToken:
    """Runtime dynamic capability proof token issued to a sandboxed plugin."""

    token_id: str
    plugin_id: str
    granted_domains: list[str]
    granted_file_scope: str
    allow_shell: bool
    issued_at: float
    expires_at: float
    token_hmac: str


@dataclass(slots=True, frozen=True)
class VerificationOutcome:
    """Integrity and signature verification outcome."""

    is_valid: bool
    trust_tier: PluginTrustTier
    error_message: str | None = None
