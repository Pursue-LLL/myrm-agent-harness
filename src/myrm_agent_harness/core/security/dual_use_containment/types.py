"""Type definitions for dual-use skill containment and artifact exfiltration shield suite.

Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class MitreAttackTactic(StrEnum):
    """MITRE ATT&CK tactic classifications for dual-use skills."""

    INITIAL_ACCESS = "initial_access"
    EXECUTION = "execution"
    PERSISTENCE = "persistence"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    CREDENTIAL_ACCESS = "credential_access"
    DISCOVERY = "discovery"
    LATERAL_MOVEMENT = "lateral_movement"
    COMMAND_AND_CONTROL = "command_and_control"
    EXFILTRATION = "exfiltration"
    IMPACT = "impact"


class SkillSensitivityLevel(StrEnum):
    """Sensitivity classification of an agent skill."""

    BENIGN = "benign"
    DUAL_USE_SENSITIVE = "dual_use_sensitive"
    MALICIOUS_PROHIBITED = "malicious_prohibited"


class ArtifactSecurityClassification(StrEnum):
    """Security classification assigned to sandbox-generated artifacts."""

    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED_ARTIFACT = "restricted_artifact"


class EgressDestinationTrust(StrEnum):
    """Trust classification of the outbound data destination."""

    ALLOWLISTED_INTERNAL = "allowlisted_internal"
    AUTHORIZED_PRIVATE_REPO = "authorized_private_repo"
    UNTRUSTED_PUBLIC_EXTERNAL = "untrusted_public_external"


@dataclass(frozen=True)
class SkillTtpTagSpec:
    """Tactical MITRE ATT&CK classification and containment requirements for a skill."""

    skill_name: str
    tactics: list[MitreAttackTactic]
    sensitivity_level: SkillSensitivityLevel
    requires_hitl_approval: bool
    quarantine_pod_enforced: bool
    description: str = ""
    identified_signatures: list[str] = field(default_factory=list)


@dataclass
class ArtifactExfiltrationAudit:
    """Audit evaluation for an attempted artifact upload/egress operation."""

    artifact_id: str
    artifact_name: str
    classification: ArtifactSecurityClassification
    target_destination: str
    destination_trust: EgressDestinationTrust
    is_blocked: bool
    violation_reason: str
    sha256_hash: str
    evaluated_at: str


@dataclass(frozen=True)
class ExecutionGateRequest:
    """Request payload to verify dual-use skill execution authorization."""

    skill_name: str
    command_line: str
    target_host_or_ip: str
    approval_token: str = ""
    is_running_in_quarantine_pod: bool = False
    context_parameters: dict[str, str | int | float | bool] = field(default_factory=dict)


@dataclass
class DualUseExecutionGateResult:
    """Outcome of pre-execution evaluation for dual-use skills."""

    permitted: bool
    requires_hitl_modal: bool
    sensitivity_level: SkillSensitivityLevel
    enforce_quarantine_pod: bool
    reason: str
    matched_tactics: list[MitreAttackTactic] = field(default_factory=list)
    hitl_prompt_warning: str = ""
