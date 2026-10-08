"""Types and models for rule cascade.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- EvidenceScopeKind: Scope boundaries for memory evidence and deterministic rules.
- EvidenceSourceKind: Source authority tiers for evidence validation.
- EvidencePermissionLevel: RBAC security boundary for multi-tenant and workspace memory access.
- FiveDimEvidenceMetadata: Five-dimensional metadata contract for pre-filtering and deterministic cascade.
- DeterministicRuleEntry: A deterministic engineering rule or constraint.
- CascadedRuleSet: Consolidated set of deterministic rules loaded hierarchically along the path tree.
- FiveDimFilterSpec: Pre-filtering specifications applied BEFORE retrieval to ensure zero leakage.
- PreFilteredEvidenceResult: Result of evaluating items against the 5-dimensional pre-filter boundary.

[POS]
Types and models for rule cascade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class EvidenceScopeKind(StrEnum):
    """Scope boundaries for memory evidence and deterministic rules."""

    GLOBAL = "global"
    ORGANIZATION = "organization"
    WORKSPACE = "workspace"
    DIRECTORY = "directory"
    FILE = "file"


class EvidenceSourceKind(StrEnum):
    """Source authority tiers for evidence validation."""

    USER_EXPLICIT = "user_explicit"  # Authority: 1.0 (Highest)
    TOOL_VERIFIED = "tool_verified"    # Authority: 0.8
    AGENT_INFERRED = "agent_inferred"  # Authority: 0.4 (Lowest)


class EvidencePermissionLevel(StrEnum):
    """RBAC security boundary for multi-tenant and workspace memory access."""

    PUBLIC = "public"
    WORKSPACE_INTERNAL = "workspace_internal"
    CONFIDENTIAL_ADMIN = "confidential_admin"


@dataclass(frozen=True)
class FiveDimEvidenceMetadata:
    """Five-dimensional metadata contract for pre-filtering and deterministic cascade."""

    scope: EvidenceScopeKind
    scope_path: str  # e.g., "/", "/workspace", "/workspace/packages/billing"
    source: EvidenceSourceKind
    source_authority: float  # 1.0, 0.8, 0.4
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    half_life_days: float = 30.0
    confidence: float = 1.0
    permission: EvidencePermissionLevel = EvidencePermissionLevel.PUBLIC


@dataclass(frozen=True)
class DeterministicRuleEntry:
    """A deterministic engineering rule or constraint."""

    rule_id: str
    title: str
    rule_content: str
    metadata: FiveDimEvidenceMetadata
    is_enforced: bool = True


@dataclass(frozen=True)
class CascadedRuleSet:
    """Consolidated set of deterministic rules loaded hierarchically along the path tree."""

    target_path: str
    inherited_rules: list[DeterministicRuleEntry]
    effective_rules_count: int
    sources_breakdown: dict[str, int]


@dataclass(frozen=True)
class FiveDimFilterSpec:
    """Pre-filtering specifications applied BEFORE retrieval to ensure zero leakage."""

    allowed_scopes: set[EvidenceScopeKind] | None = None
    scope_path_prefix: str | None = None
    min_authority: float = 0.0
    min_confidence: float = 0.0
    required_permission: EvidencePermissionLevel | None = None
    max_decay_age_days: float | None = None


@dataclass(frozen=True)
class PreFilteredEvidenceResult:
    """Result of evaluating items against the 5-dimensional pre-filter boundary."""

    items: list[DeterministicRuleEntry]
    total_evaluated: int
    passed_count: int
    rejection_reasons: dict[str, int]
