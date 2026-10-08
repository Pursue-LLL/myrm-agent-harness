"""Type definitions for NVIDIA SkillSpector Level Skill Supply Chain Security Scanner."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SkillSafetyRating(StrEnum):
    """NVIDIA SkillSpector safety rating tiers."""

    A_VERIFIED_SECURE = "A_VERIFIED_SECURE"  # Passed all AST/prompt checks, granted green shield
    B_RESTRICTED_ACCESS = "B_RESTRICTED_ACCESS"  # Low-risk declarations, confined to restricted sandbox
    C_SUSPICIOUS = "C_SUSPICIOUS"  # Questionable network or file access, requires explicit human opt-in
    D_MALICIOUS_REJECTED = "D_MALICIOUS_REJECTED"  # Hard indicators of prompt injection, reverse shell, or credential leak


class FindingSeverity(StrEnum):
    """Severity of a discovered security finding."""

    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FindingCategory(StrEnum):
    """Category of vulnerability or supply chain risk."""

    CREDENTIAL_HARVESTING = "CREDENTIAL_HARVESTING"
    COMMAND_INJECTION = "COMMAND_INJECTION"
    UNAUTHORIZED_EGRESS = "UNAUTHORIZED_EGRESS"
    PROMPT_INJECTION = "PROMPT_INJECTION"
    ARBITRARY_CODE_EXECUTION = "ARBITRARY_CODE_EXECUTION"


@dataclass(slots=True, frozen=True)
class SecurityFinding:
    """Detailed security finding identified in skill manifest, prompt, or code."""

    rule_id: str
    category: FindingCategory
    severity: FindingSeverity
    file_name: str
    line_number: int
    matched_content: str
    description: str


@dataclass(slots=True, frozen=True)
class SandboxProfile:
    """Synthesized least-privilege sandbox enforcement configuration."""

    network_egress_allowed: bool
    allowed_domains: list[str] = field(default_factory=list)
    read_only_filesystem: bool = True
    allowed_write_paths: list[str] = field(default_factory=list)
    capabilities_dropped: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class SkillScanReport:
    """Comprehensive security evaluation report for an AI skill package."""

    skill_id: str
    skill_version: str
    safety_rating: SkillSafetyRating
    is_shield_verified: bool
    findings: list[SecurityFinding]
    sandbox_profile: SandboxProfile
    scanned_at: float
