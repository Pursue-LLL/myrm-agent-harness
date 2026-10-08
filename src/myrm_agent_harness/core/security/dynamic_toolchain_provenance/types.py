"""
[POS] src/myrm_agent_harness/core/security/dynamic_toolchain_provenance/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] ProvenanceStatus, ASTViolationType, ASTScanFinding, SkillProvenanceManifest, SandboxConfinementPolicy, ToolchainVerificationDecision, DynamicToolchainMetrics

Data structures and domain types for Dynamic Toolchain Supply Chain Provenance & Pre-Install Sandbox Hardening.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ProvenanceStatus(StrEnum):
    """Cryptographic provenance verification status."""

    VERIFIED = "VERIFIED"
    UNTRUSTED_PUBLISHER = "UNTRUSTED_PUBLISHER"
    HASH_MISMATCH = "HASH_MISMATCH"
    SIGNATURE_INVALID = "SIGNATURE_INVALID"
    UNSIGNED = "UNSIGNED"


class ASTViolationType(StrEnum):
    """Categories of suspicious or dangerous constructs discovered via AST scan."""

    DANGEROUS_EXEC = "DANGEROUS_EXEC"
    UNDECLARED_SOCKET = "UNDECLARED_SOCKET"
    ENV_CREDENTIAL_PROBE = "ENV_CREDENTIAL_PROBE"
    PROCESS_SPAWN = "PROCESS_SPAWN"
    OBFUSCATED_PAYLOAD = "OBFUSCATED_PAYLOAD"
    SYNTAX_ERROR = "SYNTAX_ERROR"


@dataclass(frozen=True)
class ASTScanFinding:
    """Individual violation found during pre-install static AST scanning."""

    violation_type: ASTViolationType
    symbol_name: str
    line_number: int
    detail: str


@dataclass(frozen=True)
class SkillProvenanceManifest:
    """Declared cryptographic provenance metadata of a dynamic toolchain skill."""

    skill_id: str
    version: str
    publisher_id: str
    source_sha256: str
    signature: str
    declared_domains: list[str] = field(default_factory=list)
    declared_paths: list[str] = field(default_factory=list)
    declared_env_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SandboxConfinementPolicy:
    """JIT least-privilege sandbox confinement profile issued for an installed skill."""

    policy_id: str
    skill_id: str
    allowed_domains: list[str]
    allowed_paths: list[str]
    allowed_env_keys: list[str]
    is_confined: bool
    created_at: float


@dataclass(frozen=True)
class ToolchainVerificationDecision:
    """Comprehensive verdict deciding whether an external skill is safe to mount."""

    skill_id: str
    provenance_status: ProvenanceStatus
    is_provenance_valid: bool
    ast_findings: list[ASTScanFinding]
    is_ast_clean: bool
    is_installation_approved: bool
    confinement_policy: SandboxConfinementPolicy | None
    explanation: str
    timestamp: float


@dataclass
class DynamicToolchainMetrics:
    """Cumulative metrics tracking dynamic toolchain security gates."""

    provenance_checks_total: int = 0
    provenance_verified_total: int = 0
    provenance_rejected_total: int = 0
    ast_scans_total: int = 0
    ast_violations_detected_total: int = 0
    confinements_issued_total: int = 0
    installations_approved_total: int = 0
    installations_blocked_total: int = 0
