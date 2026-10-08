"""Type definitions for High-Risk Surface CI Gate and Skill Change SecOps Audit.

[INPUT]
- None.

[OUTPUT]
- RiskCategory, SurfaceLabel, SkillPermission
- SurfaceMatch, DiffSurfaceAnalysisResult, SkillIntegrityManifest, SkillAuditReport
- SecOpsAuditError, SkillTamperingError, UnsignedSkillError

[POS]
- Harness core security module inspired by Mike Julian SecOps review practices.
- Treats Agent Skills and security/API attack surfaces as high-risk surfaces requiring
  automated tagging and multi-party review gates.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class RiskCategory(StrEnum):
    """Categorization of high-risk codebase surfaces."""

    PUBLIC_API = "public_api"
    AUTH_SECURITY = "auth_security"
    MCP_CONFIG = "mcp_config"
    DATABASE_MIGRATION = "database_migration"
    SKILL_MUTATION = "skill_mutation"
    GENERAL_CODE = "general_code"


class SurfaceLabel(StrEnum):
    """Labels applied automatically during CI/PR scanning."""

    RISK_HIGH_SURFACE = "⚠️ risk:high-surface"
    SEC_AUTH_CHANGE = "🔒 sec:auth-change"
    MCP_CONFIG_MUTATION = "🔌 mcp:config-mutation"
    DB_MIGRATION_SURFACE = "🗄️ db:migration-surface"
    AGENT_SKILL_MUTATION = "🧠 agent:skill-mutation"


class SkillPermission(StrEnum):
    """Sensitive capability permissions requested by an Agent Skill."""

    EXECUTE_SHELL = "execute_shell"
    NETWORK_EGRESS = "network_egress"
    FILE_SYSTEM_WRITE = "file_system_write"
    ENV_SECRET_READ = "env_secret_read"


@dataclass(frozen=True, slots=True)
class SurfaceMatch:
    """Specific file path match against a risk rule."""

    path: str
    category: RiskCategory
    suggested_label: SurfaceLabel
    reason: str


@dataclass(frozen=True, slots=True)
class DiffSurfaceAnalysisResult:
    """Comprehensive result of surface risk analysis over a set of modified files."""

    total_files_scanned: int
    high_risk_detected: bool
    requires_multi_party_review: bool
    applied_labels: tuple[str, ...]
    matches: tuple[SurfaceMatch, ...]
    scanned_at: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class SkillIntegrityManifest:
    """Cryptographic manifest binding a skill definition to its author and permissions."""

    skill_name: str
    skill_version: str
    content_hash: str
    declared_permissions: tuple[SkillPermission, ...]
    signature: str
    signed_by: str
    signed_at: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class SkillAuditReport:
    """Audit report examining a SKILL.md before execution or mounting."""

    skill_name: str
    is_valid: bool
    content_hash: str
    detected_permissions: tuple[SkillPermission, ...]
    unapproved_permissions: tuple[SkillPermission, ...]
    signature_verified: bool
    requires_user_consent: bool
    violations: tuple[str, ...]


class SecOpsAuditError(Exception):
    """Base exception for SecOps audit and high-risk CI gates."""


class SkillTamperingError(SecOpsAuditError):
    """Raised when a Skill's content hash does not match its cryptographic signature."""


class UnsignedSkillError(SecOpsAuditError):
    """Raised when an untrusted third-party skill lacks an integrity signature."""
