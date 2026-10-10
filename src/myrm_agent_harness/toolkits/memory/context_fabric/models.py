"""Domain models for Cross-Source Work Context Fabric & Project Entity Linker Suite.

[INPUT]
- Multi-source work events, entity tags, project registry entries, and insights.

[OUTPUT]
- SourceKind, WorkEvent, WorkContextEntity, ProjectRegistryEntry, EntityMatchResult,
  InsightCandidate, InsightSinkRecord.

[POS]
- Domain models for Item 153 CrossSourceWorkContextFabricAndProjectEntityLinkerSuite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SourceKind(str, Enum):
    """Supported multi-source context fabric data origins."""

    FEISHU = "feishu"
    DINGTALK = "dingtalk"
    LINEAR = "linear"
    LOCAL_FILE = "local_file"
    CALENDAR = "calendar"
    GIT = "git"
    CUSTOM = "custom"


@dataclass(frozen=True)
class WorkEvent:
    """Raw work event ingested from connected external tools or local directories."""

    event_id: str
    source_kind: SourceKind
    source_id: str
    title: str
    raw_content: str
    author: str = ""
    timestamp_ms: int = 0
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkContextEntity:
    """Structured entity extracted from unstructured work events."""

    entity_id: str
    entity_type: str  # project | person | module | commitment | blocker
    name: str
    role_or_relation: str = ""
    temporal_anchor: str | None = None
    status: str = "active"
    confidence: float = 1.0
    evidence_snippet: str = ""


@dataclass(frozen=True)
class ProjectRegistryEntry:
    """Canonical active project registered within the workspace."""

    project_id: str
    name: str
    aliases: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    description: str = ""
    status: str = "active"  # active | archived | planned


@dataclass(frozen=True)
class EntityMatchResult:
    """Matching score and attribution evidence linking text to a canonical project."""

    project_id: str
    project_name: str
    confidence_score: float
    matched_terms: tuple[str, ...] = ()
    evidence_snippet: str = ""
    is_definitive: bool = False


@dataclass(frozen=True)
class InsightCandidate:
    """Actionable insight or conclusion derived from processing cross-source events."""

    insight_id: str
    title: str
    content: str
    source_event_ids: tuple[str, ...] = ()
    target_project_id: str | None = None
    impact_level: str = "medium"  # critical | high | medium | low


@dataclass(frozen=True)
class InsightSinkRecord:
    """Audit record confirming persistent sinking of an insight into project memory."""

    record_id: str
    insight_id: str
    project_id: str
    sink_target: str
    written_at_ms: int
    provenance_tag: str
    rendered_bullet: str
