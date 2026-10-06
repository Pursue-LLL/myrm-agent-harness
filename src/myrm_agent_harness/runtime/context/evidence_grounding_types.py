"""Type definitions for evidence-based locator grounding protocol and anti-hallucination gate.

Defines structured locators (line ranges, primary keys, offsets), search candidates,
verified source evidence, and grounding audit results.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class LocatorKind(StrEnum):
    """Specification of locator coordinate semantics."""

    LINE_RANGE = "line_range"
    PRIMARY_KEY = "primary_key"
    CHAR_OFFSET = "char_offset"
    DIRECTORY = "directory"


@dataclass(frozen=True)
class StructuredLocator:
    """High-precision coordinate pointer for source artifact grounding."""

    kind: LocatorKind
    line_range: tuple[int, int] | None = None
    key_fields: dict[str, str] | None = None
    char_range: tuple[int, int] | None = None

    def to_display_string(self) -> str:
        """Render human and machine readable locator coordinate."""
        if self.kind == LocatorKind.LINE_RANGE and self.line_range:
            return f"L{self.line_range[0]}-L{self.line_range[1]}"
        if self.kind == LocatorKind.PRIMARY_KEY and self.key_fields:
            fields_str = ",".join(f"{k}={v}" for k, v in sorted(self.key_fields.items()))
            return f"pk({fields_str})"
        if self.kind == LocatorKind.CHAR_OFFSET and self.char_range:
            return f"chars({self.char_range[0]}-{self.char_range[1]})"
        return "root"


@dataclass(frozen=True)
class SearchCandidateHit:
    """Provisional candidate hit returned from retrieval or search."""

    hit_id: str
    source_uri: str
    locator: StructuredLocator
    score: float
    snippet_preview: str
    is_verified: bool = False


@dataclass(frozen=True)
class VerifiedEvidence:
    """Authentic, verified evidence re-read from the canonical source object."""

    evidence_id: str
    hit_id: str
    source_uri: str
    locator: StructuredLocator
    raw_content: str
    content_hash: str
    verified_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class GroundingAuditResult:
    """Outcome of the anti-hallucination grounding verification gate."""

    is_grounded: bool
    total_claims_count: int
    grounded_claims_count: int
    missing_evidence_reasons: list[str]
    confidence_score: float
