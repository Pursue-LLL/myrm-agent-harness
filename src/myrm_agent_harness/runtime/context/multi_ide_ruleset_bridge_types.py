"""Type definitions for Multi-IDE Universal Ruleset Parser and Trae Rules Compatibility Bridge.

Defines schemas for IDE ecosystem classification, unified rule representation,
multi-source deduplication, and migration readiness reporting.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- IdeEcosystemKind: Supported AI IDE or agent assistant specification ecosystem.
- UniversalIdeRuleEntry: A normalized rule specification ingested from any IDE ecosystem.
- MigrationReadinessReport: Telemetry report assessing cross-IDE rule ingestion and migration health.

[POS]
Type definitions for Multi-IDE Universal Ruleset Parser and Trae Rules Compatibility Bridge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class IdeEcosystemKind(StrEnum):
    """Supported AI IDE or agent assistant specification ecosystem."""

    MYRM = "myrm"
    TRAE = "trae"
    CURSOR = "cursor"
    CLAUDE = "claude"
    GOOSE = "goose"
    WINDSURF = "windsurf"
    COPILOT = "copilot"
    CLINE = "cline"
    GENERIC = "generic"


@dataclass(frozen=True)
class UniversalIdeRuleEntry:
    """A normalized rule specification ingested from any IDE ecosystem."""

    ecosystem: IdeEcosystemKind
    file_path: str
    rule_name: str
    content: str
    priority_weight: int
    globs: tuple[str, ...]
    checksum_sha256: str


@dataclass(frozen=True)
class MigrationReadinessReport:
    """Telemetry report assessing cross-IDE rule ingestion and migration health."""

    discovered_ecosystems: tuple[IdeEcosystemKind, ...]
    total_rules_scanned: int
    effective_rules_count: int
    deduplicated_count: int
    compatibility_score: float
    readiness_summary_banner: str
    ecosystem_breakdown: dict[str, int] = field(default_factory=dict)
