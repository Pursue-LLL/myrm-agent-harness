"""Data models for Experience Compounding and Knowledge Condensation Suite.

[POS]
Defines typed entities for compounding experience items, abstracted Golden Rules,
and execution telemetry reports.

[INPUT]
- dataclasses, enum, time, typing

[OUTPUT]
- ExperienceItemState, CompoundedExperienceItem, GoldenRuleItem
- CondensationReport, AnnealingReport
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class ExperienceItemState(StrEnum):
    """Lifecycle state of an experience or memory item."""

    ACTIVE = "active"
    CONDENSED_ARCHIVED = "condensed_archived"
    COLD_TIERED = "cold_tiered"
    DEPRECATED = "deprecated"


@dataclass
class CompoundedExperienceItem:
    """Memory item with compounding weight tracking and lease metadata."""

    item_id: str
    content: str
    topic: str
    base_weight: float = 1.0
    compounded_weight: float = 1.0
    peak_weight: float = 1.0
    hit_count: int = 0
    adoption_count: int = 0
    last_adopted_at: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    half_life_days: float = 14.0
    state: ExperienceItemState = ExperienceItemState.ACTIVE
    is_pinned: bool = False
    is_temporary: bool = False
    tags: list[str] = field(default_factory=list)

    def is_active(self) -> bool:
        """Return True if item actively participates in hot retrieval."""
        return self.state == ExperienceItemState.ACTIVE


@dataclass
class GoldenRuleItem:
    """Higher-order principle distilled from multiple micro-fragments with lineage."""

    rule_id: str
    topic: str
    rule_statement: str
    rationale: str
    confidence_score: float
    source_fragment_ids: list[str]
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass
class CondensationReport:
    """Execution telemetry report from knowledge condensation run."""

    report_id: str
    clusters_found: int
    rules_generated: int
    fragments_archived: int
    compression_ratio: float
    details: list[str] = field(default_factory=list)


@dataclass
class AnnealingReport:
    """Telemetry report of obsolete context annealing and cold tiering."""

    report_id: str
    inspected_count: int
    active_lease_exempt_count: int
    cold_tiered_count: int
    decayed_items: list[str] = field(default_factory=list)
