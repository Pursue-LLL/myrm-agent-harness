"""Type definitions for Ambiguity Clarification Probe and Private Entity Graph Backtracking Suite.

Provides immutable data contracts for ambiguity detection levels, clarification inquiries,
entity graph matches, and synthesized outline dossiers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import time


class AmbiguityLevel(StrEnum):
    """Classification of prompt ambiguity severity."""

    CLEAR = "clear"
    MODERATE_AMBIGUOUS = "moderate_ambiguous"
    HIGHLY_AMBIGUOUS = "highly_ambiguous"


@dataclass(frozen=True)
class ClarificationQuestion:
    """Structured inquiry posing critical missing constraints to the user."""

    dimension: str
    question: str
    default_options: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class EntityGraphMatch:
    """Discovered private asset entity matched through graph backtracking."""

    entity_name: str
    entity_type: str
    source_identifier: str
    confidence_score: float
    key_facts: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ClarificationProbeResult:
    """Outcome of pre-flight ambiguity inspection on incoming user prompt."""

    level: AmbiguityLevel
    is_ambiguous: bool
    detected_entities: tuple[str, ...]
    clarification_questions: tuple[ClarificationQuestion, ...]
    needs_backtracking: bool
    reason: str


@dataclass(frozen=True)
class BacktrackedContextDossier:
    """Comprehensive factual dossier retrieved from private knowledge assets."""

    target_entity: str
    matches: tuple[EntityGraphMatch, ...]
    synthesized_facts: tuple[str, ...]
    suggested_outline: str
    assembled_at: float = field(default_factory=time.time)
