# [INPUT] None (Foundation domain types for persona memory drift audit)
# [OUTPUT] PersonaFileKind, BadSmellCategory, AuditLineSmell, FileDriftAuditResult, ReconciliationDiffPlan, PurificationExecutionResult
# [POS] Domain data structures for line-by-line reality reconciliation, bad-smell tagging, and human-confirmed purification

"""Domain types for deterministic persona memory drift audit and line-by-line reconciliation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

PersonaFileKind = Literal["SOUL", "USER", "MEMORY", "AGENTS", "UNKNOWN"]

BadSmellCategory = Literal[
    "STALE",          # Outdated facts or dead workspace references
    "DUPLICATE",      # Redundant repetition of identical or near-identical preferences
    "CONTRADICTORY",  # Mutually incompatible instructions fighting for dominance
    "NO_OP",          # Chit-chat, conversational filler, or non-operative statements
]


@dataclass(frozen=True)
class AuditLineSmell:
    """A single identified bad-smell flaw on a specific line of a persona/memory file."""

    line_number: int
    original_text: str
    smell: BadSmellCategory
    explanation: str
    proposed_resolution: str
    confidence: float = 0.85


@dataclass(frozen=True)
class FileDriftAuditResult:
    """Audit report for a single persona or memory file."""

    file_path: str
    file_kind: PersonaFileKind
    total_lines: int
    flagged_lines: list[AuditLineSmell]
    estimated_token_waste: int
    healthy_score: int  # 0 - 100

    @property
    def has_flaws(self) -> bool:
        return len(self.flagged_lines) > 0


@dataclass(frozen=True)
class ReconciliationDiffPlan:
    """A proposed red/green line-level diff plan requiring human confirmation before apply."""

    file_path: str
    file_kind: PersonaFileKind
    original_content: str
    purified_content: str
    removed_line_numbers: list[int]
    modified_line_numbers: dict[int, str]
    net_tokens_saved: int
    requires_confirmation: bool = True


@dataclass(frozen=True)
class PurificationExecutionResult:
    """Result of applying a confirmed reconciliation diff plan to disk."""

    file_path: str
    applied: bool
    backup_path: str | None
    lines_removed: int
    tokens_saved: int
    message: str
