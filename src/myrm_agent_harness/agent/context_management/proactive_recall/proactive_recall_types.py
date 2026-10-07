"""Strongly typed contracts for Context Gap Auto Probe and Proactive Recall Gate (Item 210).

[INPUT]
- None (self-contained, standard library only).

[OUTPUT]
- EntityType: Classification of pruned context entities.
- PrunedEntityRecord: Tracked ledger entry for an expunged or compacted entity.
- ContextGapDetection: Detected reference to a pruned entity missing from the active window.
- ProactiveRecallNudgeConfig: Tunable configuration for gap probing and recall nudges.
- ProactiveRecallProbeResult: Structured outcome of static gap probing and recall nudge rendering.

[POS]
- Eliminates agent cognitive blind spots and memory amnesia by tracking pruned entities,
- detecting references to expunged context, and injecting proactive retrieval hints.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class EntityType(str, enum.Enum):
    """Categorization of entities tracked in the pruned footprint ledger."""

    FILE_PATH = "file_path"
    IDENTIFIER = "identifier"
    ERROR_CODE = "error_code"
    CONFIG_KEY = "config_key"
    URL = "url"
    GENERIC = "generic"


@dataclass(frozen=True, slots=True)
class PrunedEntityRecord:
    """Ledger entry recording an entity stripped or compacted from active memory."""

    entity_name: str
    entity_type: EntityType
    turn_index: int
    summary_hint: str = ""
    recorded_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        """Serializes record to dictionary."""
        return {
            "entity_name": self.entity_name,
            "entity_type": self.entity_type.value,
            "turn_index": self.turn_index,
            "summary_hint": self.summary_hint,
            "recorded_at": self.recorded_at,
        }


@dataclass(frozen=True, slots=True)
class ContextGapDetection:
    """Represents a discovered cognitive gap where an agent references a pruned entity."""

    entity_name: str
    entity_type: EntityType
    turn_index: int
    context_snippet: str
    confidence: float = 1.0

    def to_dict(self) -> dict[str, object]:
        """Serializes gap detection to dictionary."""
        return {
            "entity_name": self.entity_name,
            "entity_type": self.entity_type.value,
            "turn_index": self.turn_index,
            "context_snippet": self.context_snippet,
            "confidence": self.confidence,
        }


@dataclass(slots=True)
class ProactiveRecallNudgeConfig:
    """Configures entity extraction thresholds and proactive recall prompt formatting."""

    min_entity_len: int = 3
    max_nudges_per_turn: int = 3
    include_xml_wrapper: bool = True
    nudge_template: str = (
        'Entity "{name}" ({entity_type}) was discussed in Turn #{turn} but pruned from active context. '
        'Use session_search tool to fetch verbatim trace if detailed history is needed.'
    )


@dataclass(slots=True)
class ProactiveRecallProbeResult:
    """Structured inspection outcome detailing context gaps and generated recall hints."""

    session_id: str
    detected_gaps: list[ContextGapDetection]
    nudge_block: str | None
    scanned_entity_count: int
    probe_latency_ms: float = 0.0

    @property
    def has_gap(self) -> bool:
        """Indicates whether any context gaps were detected."""
        return len(self.detected_gaps) > 0

    def to_dict(self) -> dict[str, object]:
        """Serializes probe result to dictionary."""
        return {
            "session_id": self.session_id,
            "has_gap": self.has_gap,
            "gap_count": len(self.detected_gaps),
            "detected_gaps": [g.to_dict() for g in self.detected_gaps],
            "nudge_block": self.nudge_block,
            "scanned_entity_count": self.scanned_entity_count,
            "probe_latency_ms": self.probe_latency_ms,
        }
