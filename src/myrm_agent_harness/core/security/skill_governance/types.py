"""Type definitions for Agent Skill Engineering Governance and Privilege Verification.

[INPUT]
- None.

[OUTPUT]
- FilesystemScope, SkillPermissionContract, SkillDriftAnalysis
- SkillGovernanceError, SkillPrivilegeEscalationError, UnapprovedSkillMountError

[POS]
- Harness core security module inspired by Mike Julian engineering SecOps governance.
- Treats Agent Skills as first-class executable code with strict permission contracts,
  detecting privilege escalation and gating mounting behind mandatory reviews.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class FilesystemScope(StrEnum):
    """Permitted filesystem boundary for a Skill."""

    READ_ONLY = "read_only"
    TASK_WORKSPACE = "task_workspace"
    FULL_ACCESS = "full_access"


@dataclass(frozen=True, slots=True)
class SkillPermissionContract:
    """Explicit permission contract declared by an Agent Skill."""

    skill_name: str
    version: str
    declared_tools: frozenset[str]
    network_egress: bool = False
    filesystem_scope: FilesystemScope = FilesystemScope.TASK_WORKSPACE
    requires_admin_review: bool = False
    registered_at: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class SkillDriftAnalysis:
    """Diff analysis between two skill versions, identifying privilege drift or escalation."""

    skill_name: str
    base_version: str | None
    target_version: str
    added_tools: frozenset[str]
    removed_tools: frozenset[str]
    escalated_permissions: tuple[str, ...]
    has_privilege_escalation: bool
    review_required: bool
    audit_findings: tuple[str, ...]
    analyzed_at: float = field(default_factory=time.time)


class SkillGovernanceError(Exception):
    """Base exception for skill engineering governance and permission gates."""


class SkillPrivilegeEscalationError(SkillGovernanceError):
    """Raised when a Skill modifies its contract to escalate privileges without authorization."""


class UnapprovedSkillMountError(SkillGovernanceError):
    """Raised when an unapproved skill with elevated permissions is mounted in runtime."""
