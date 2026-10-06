# [POS] src/myrm_agent_harness/toolkits/memory/dual_track_extraction/types.py
# [INPUT] dataclasses, enum.StrEnum, datetime, typing
# [OUTPUT] ExtractionTrackKind, ExtractionDestiny, ExtractedProceduralRule, ExtractedUserFact, ExtractionDestinyReport

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class ExtractionTrackKind(StrEnum):
    """Semantic track category identified from input utterance."""

    FACT_PROFILE = "fact_profile"
    PROCEDURAL_RULE = "procedural_rule"
    DUAL_TRACK = "dual_track"
    NO_SIGNAL = "no_signal"


class ExtractionDestiny(StrEnum):
    """Deterministic routing destination for the extraction output."""

    STORED_SEMANTIC = "stored_semantic"
    STORED_PROCEDURAL = "stored_procedural"
    STORED_DUAL = "stored_dual"
    DISCARDED_NO_SIGNAL = "discarded_no_signal"


@dataclass(frozen=True)
class ExtractedProceduralRule:
    """Actionable operational rule or troubleshooting guideline (When/If X, Do Y)."""

    rule_id: str
    name: str
    trigger_condition: str
    action_guideline: str
    domain: str = "general"
    confidence: float = 0.85
    raw_source: str = ""


@dataclass(frozen=True)
class ExtractedUserFact:
    """Declarative static fact, preference, or identity profile."""

    fact_id: str
    entity: str
    attribute: str
    value: str
    confidence: float = 0.85
    raw_source: str = ""


@dataclass(frozen=True)
class ExtractionDestinyReport:
    """Transparent routing report eliminating silent drop ambiguity."""

    destiny: ExtractionDestiny
    track: ExtractionTrackKind
    extracted_facts: list[ExtractedUserFact] = field(default_factory=list)
    extracted_rules: list[ExtractedProceduralRule] = field(default_factory=list)
    discard_reason: str = ""
    raw_input_text: str = ""
    processed_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
