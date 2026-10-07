"""Full-duplex voice requirement discovery and structured spec extractor types.

Defines schemas for voice consultant phases, raw speech transcript turns,
module definitions, and structured technical plan/spec artifacts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class VoiceConsultantPhase(StrEnum):
    """Lifecycle phase of the voice requirement consultation session."""

    EXPLORATION = "exploration"
    DEEP_DIVE = "deep_dive"
    TRADE_OFF_ANALYSIS = "trade_off_analysis"
    FINAL_ALIGNMENT = "final_alignment"
    SPEC_GENERATED = "spec_generated"


@dataclass(frozen=True)
class VoiceTranscriptTurn:
    """An individual spoken turn recorded in the full-duplex session."""

    turn_id: str
    speaker: str
    transcript_text: str
    timestamp_ms: int
    is_interruption: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SpecModuleDefinition:
    """Formal definition of a functional module derived from voice discussion."""

    module_name: str
    responsibility: str
    technical_stack: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]


@dataclass(frozen=True)
class StructuredPlanSpec:
    """Rigorous engineering specification distilled from voice requirement discussions."""

    spec_id: str
    project_title: str
    executive_summary: str
    core_modules: tuple[SpecModuleDefinition, ...]
    data_flow_overview: str
    explicit_non_goals: tuple[str, ...]
    kanban_tasks: tuple[str, ...]
    source_turn_count: int
    created_at_ms: int


@dataclass(frozen=True)
class SpecExtractionResult:
    """Result of distilling a voice transcript buffer into a formal spec."""

    success: bool
    spec: StructuredPlanSpec | None = None
    validation_errors: tuple[str, ...] = field(default_factory=tuple)
    turnaround_ms: int = 0
