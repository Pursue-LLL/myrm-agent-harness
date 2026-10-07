"""Types for pluggable context projection and entry transform pipeline.

Defines schemas for custom context entries, semantic projections, transform stage
audits, and complete pipeline execution reports for visual inspection.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from .append_only_compaction_types import ContextLogEntry


class TransformStageKind(StrEnum):
    """Pipeline progression stages."""

    RAW_SELECTION = "RAW_SELECTION"
    ENTRY_TRANSFORMS = "ENTRY_TRANSFORMS"
    CUSTOM_PROJECTION = "CUSTOM_PROJECTION"
    FINAL_ASSEMBLY = "FINAL_ASSEMBLY"


@dataclass(frozen=True)
class CustomContextEntry:
    """Arbitrary domain entity recorded by skills or extensions."""

    entry_id: str
    entry_type: str
    payload: dict[str, str] = field(default_factory=dict)
    created_at: str = ""


@dataclass(frozen=True)
class PipelineStageAuditRecord:
    """Detailed visual debugger audit snapshot for a single transform stage."""

    stage: TransformStageKind
    transformer_name: str
    entries_count_before: int
    entries_count_after: int
    tokens_before: int
    tokens_after: int
    token_delta: int
    duration_ms: float
    description: str


@dataclass(frozen=True)
class ContextPipelineExecutionReport:
    """Full pipeline execution artifact consumable by models and WebUI visual inspectors."""

    original_entries_count: int
    final_entries: list[ContextLogEntry]
    total_tokens: int
    tokens_saved: int
    stage_audits: list[PipelineStageAuditRecord]
