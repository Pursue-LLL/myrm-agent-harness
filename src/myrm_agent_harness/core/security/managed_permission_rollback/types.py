"""Type definitions for Enterprise Role-Based Permission Templates, Checkpoint Rollback, and Connectors Hub.

[POS] src/myrm_agent_harness/core/security/managed_permission_rollback/types.py
[INPUT] enum, dataclasses
[OUTPUT] EnterpriseRoleTemplate, PermissionActionRule, RolePermissionPolicy, ComplianceDriftReport, FileStateSnapshot, SessionCheckpoint, RollbackDiffSummary, ConnectorChannelType, ConnectorStatus, ManagedConnectorMeta
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class EnterpriseRoleTemplate(StrEnum):
    """Four canonical enterprise role-based permission presets."""

    AUDITOR = "AUDITOR"
    SAFE_COLLABORATOR = "SAFE_COLLABORATOR"
    FULL_STACK_DEVELOPER = "FULL_STACK_DEVELOPER"
    AUTONOMOUS_OPS = "AUTONOMOUS_OPS"


class PermissionActionRule(StrEnum):
    """Enforcement policy for an action dimension or tool category."""

    ALWAYS_ALLOW = "ALWAYS_ALLOW"
    ASK_HUMAN = "ASK_HUMAN"
    DENY = "DENY"


class ConnectorChannelType(StrEnum):
    """Supported managed ecosystem integration channels."""

    DISCORD = "DISCORD"
    GITHUB = "GITHUB"
    SLACK = "SLACK"
    NOTION = "NOTION"
    JIRA = "JIRA"
    FEISHU = "FEISHU"


class ConnectorStatus(StrEnum):
    """Health and lifecycle state of a managed external connector."""

    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    EXPIRED = "EXPIRED"
    DISCONNECTED = "DISCONNECTED"


@dataclass(slots=True, frozen=True)
class RolePermissionPolicy:
    """Declared policy boundary corresponding to an enterprise role."""

    role: EnterpriseRoleTemplate
    display_name: str
    description: str
    rules: dict[str, PermissionActionRule]  # dimension/category -> enforcement
    max_network_egress_domains: int
    allow_shell_execution: bool
    require_hitl_on_external_sends: bool
    allowed_filesystem_roots: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class ComplianceDriftItem:
    """Specific privilege deviation between assigned template and active runtime."""

    target: str
    template_rule: str
    actual_rule: str
    is_excessive: bool
    remediation_hint: str


@dataclass(slots=True, frozen=True)
class ComplianceDriftReport:
    """Audit report comparing runtime configuration against an enterprise template baseline."""

    agent_id: str
    assigned_role: EnterpriseRoleTemplate
    is_compliant: bool
    drift_score: float  # 0.0 (fully compliant) to 1.0 (severe drift)
    deviations: list[ComplianceDriftItem] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class FileStateSnapshot:
    """Atomic state of a single file in the workspace at checkpoint creation."""

    relative_path: str
    content_hash: str
    content_bytes: bytes


@dataclass(slots=True, frozen=True)
class SessionCheckpoint:
    """Immutable session checkpoint capturing filesystem state and short-term memory."""

    checkpoint_id: str
    session_id: str
    label: str
    created_at: float
    file_snapshots: dict[str, FileStateSnapshot] = field(default_factory=dict)
    memory_state: dict[str, str] = field(default_factory=dict)
    active_role: EnterpriseRoleTemplate = EnterpriseRoleTemplate.SAFE_COLLABORATOR


@dataclass(slots=True, frozen=True)
class RollbackDiffSummary:
    """Audit trail detailing the exact changes restored upon a checkpoint rollback."""

    checkpoint_id: str
    session_id: str
    reverted_files_count: int
    restored_memory_keys_count: int
    modified_paths: list[str] = field(default_factory=list)
    rolled_back_at: float = 0.0


@dataclass(slots=True, frozen=True)
class ManagedConnectorMeta:
    """Metadata and health heartbeat information for an external channel connector."""

    connector_id: str
    channel_type: ConnectorChannelType
    display_name: str
    status: ConnectorStatus
    last_heartbeat_at: float
    token_expires_at: float | None = None
    account_identifier: str = ""
