"""Data contracts and types for persona semantic conflict probe and mutual exclusion resolver.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- PersonaSourceTier: Source tier of persona configuration indicating inheritance precedence.
- PolarityDimension: Semantic polarity dimensions where personalities can clash.
- PersonaSnippet: An individual persona snippet or directive extracted from system or user prompt.
- PersonaConflictFinding: A detected semantic conflict between two antagonistic persona directives.
- ArbitratedPersonaResult: Result of mutual exclusion resolution yielding an unified, non-conflicting
  persona.

[POS]
Data contracts and types for persona semantic conflict probe and mutual exclusion resolver.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PersonaSourceTier(StrEnum):
    """Source tier of persona configuration indicating inheritance precedence."""

    SYSTEM_DEFAULT = "system_default"  # Base built-in presets (Lowest priority: 10)
    WORKSPACE_RULE = "workspace_rule"  # Project/Workspace level rules (Medium priority: 50)
    USER_CUSTOM = "user_custom"  # User explicit persona definition (High priority: 100)
    SESSION_OVERRIDE = "session_override"  # In-session turn dynamic override (Highest priority: 200)


class PolarityDimension(StrEnum):
    """Semantic polarity dimensions where personalities can clash."""

    GENTLE_VS_BLUNT = "gentle_vs_blunt"  # Soft/cute/sweet vs rough/blunt/harsh
    VERBOSITY_VS_TERSE = "verbosity_vs_terse"  # Highly elaborate vs ultra-compact/terse
    SUBMISSIVE_VS_OPINIONATED = "submissive_vs_opinionated"  # Sycophantic/submissive vs authoritative/strong opinions
    FORMAL_VS_CASUAL = "formal_vs_casual"  # Extremely formal/ceremonial vs highly colloquial/street slang


@dataclass(frozen=True)
class PersonaSnippet:
    """An individual persona snippet or directive extracted from system or user prompt."""

    snippet_id: str
    source_tier: PersonaSourceTier
    content: str
    priority_weight: int = 10


@dataclass(frozen=True)
class PersonaConflictFinding:
    """A detected semantic conflict between two antagonistic persona directives."""

    dimension: PolarityDimension
    dominant_snippet: PersonaSnippet
    subordinate_snippet: PersonaSnippet
    conflicting_keywords_dominant: tuple[str, ...] = field(default_factory=tuple)
    conflicting_keywords_subordinate: tuple[str, ...] = field(default_factory=tuple)
    explanation: str = ""


@dataclass(frozen=True)
class ArbitratedPersonaResult:
    """Result of mutual exclusion resolution yielding an unified, non-conflicting persona."""

    resolved_persona_text: str
    retained_snippets: tuple[PersonaSnippet, ...]
    dropped_conflicting_snippets: tuple[PersonaSnippet, ...]
    conflicts_detected: tuple[PersonaConflictFinding, ...]
    is_conflict_free: bool
