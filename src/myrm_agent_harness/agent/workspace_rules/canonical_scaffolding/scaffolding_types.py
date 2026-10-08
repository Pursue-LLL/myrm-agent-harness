"""Canonical agent workspace scaffolding, sniffer, and sandbox encapsulation types.

[INPUT]
- None (defines pure contract types, dataclasses, and enums).

[OUTPUT]
- Strongly typed declarations for workspace ecosystems, scaffolding manifests,
  sniffing results, sandbox encapsulation records, and interoperability reports.

[POS]
- Harness workspace rules in agent/workspace_rules/canonical_scaffolding/scaffolding_types.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Mapping, Sequence


class WorkspaceEcosystemSource(str, Enum):
    """Identified upstream ecosystem or origin architecture of an agent workspace."""

    OPEN_CLAW = "open_claw"
    META_MUSE = "meta_muse"
    HERMES = "hermes"
    CURSOR_WINDSURF = "cursor_windsurf"
    CANONICAL_MYRM = "canonical_myrm"
    GENERIC_PROJECT = "generic_project"


class EncapsulationSecurityLevel(str, Enum):
    """Security classification after scanning untrusted imported workspaces."""

    SAFE = "safe"
    SANITIZED = "sanitized"
    QUARANTINED = "quarantined"


@dataclass(frozen=True)
class ScaffoldingFileEntry:
    """Represents a discovered or generated file within a workspace scaffolding."""

    relative_path: str
    role: str  # e.g., "soul", "user", "memory", "heartbeat", "rule", "skill"
    content_char_count: int = 0
    is_required: bool = False
    digest_sha256: str = ""


@dataclass(frozen=True)
class CanonicalScaffoldingManifest:
    """Canonical representation of an agent workspace scaffolding topology."""

    workspace_root: str
    ecosystem_origin: WorkspaceEcosystemSource
    soul_file: str | None = None
    user_file: str | None = None
    memory_file: str | None = None
    heartbeat_file: str | None = None
    agents_dir: str | None = None
    rules_dir: str | None = None
    skills_dir: str | None = None
    context_dir: str | None = None
    all_files: Sequence[ScaffoldingFileEntry] = field(default_factory=tuple)
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TopologyValidationReport:
    """Report produced by validating a directory against the canonical workspace scaffolding."""

    is_canonical: bool
    ecosystem_detected: WorkspaceEcosystemSource
    missing_recommended_files: Sequence[str] = field(default_factory=tuple)
    missing_required_files: Sequence[str] = field(default_factory=tuple)
    health_score: float = 1.0  # 0.0 - 1.0
    actionable_hints: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class EcosystemSniffResult:
    """Detailed fingerprinting result of an imported or scanned workspace directory."""

    matched_ecosystem: WorkspaceEcosystemSource
    confidence: float
    signature_evidence: Sequence[str]
    detected_persona_title: str = "Standard Assistant"
    extracted_rule_count: int = 0
    extracted_skill_count: int = 0
    has_custom_memory: bool = False


@dataclass(frozen=True)
class SandboxSecurityFinding:
    """Individual security vulnerability or injection vector discovered during encapsulation."""

    severity: str  # "HIGH", "CRITICAL", "MEDIUM", "LOW"
    file_path: str
    pattern_matched: str
    description: str
    remediation_applied: str = "redacted"


@dataclass(frozen=True)
class SandboxEncapsulationRecord:
    """Encapsulation voucher securing an untrusted workspace in a user-dedicated sandbox volume."""

    source_path: str
    encapsulated_sandbox_root: str
    security_level: EncapsulationSecurityLevel
    findings: Sequence[SandboxSecurityFinding] = field(default_factory=tuple)
    sanitized_file_count: int = 0
    is_safe_to_execute: bool = True
    quarantine_reason: str | None = None


@dataclass(frozen=True)
class EcosystemInteroperabilityReport:
    """Comparison matrix and handover guide answering differences between agent products."""

    product_name: str
    comparison_summary: str
    shared_philosophies: Sequence[str]
    divergences: Sequence[str]
    migration_friction: str  # "ZERO", "LOW", "MODERATE"
    recommended_migration_steps: Sequence[str]
