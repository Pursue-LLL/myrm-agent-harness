"""Zero-LLM citation marker audit for streamed assistant answers.

[INPUT]

[OUTPUT]
- CitationAuditResult: marker counts (total / valid / unresolved)
- audit_citation_markers: verify fullwidth 【N】 indices against source count

[POS]
Shared streaming helper; used by server persistence and deep research report audit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_CITATION_MARKER_RE = re.compile(r"\u3010(\d+)\u3011")


@dataclass(frozen=True, slots=True)
class CitationAuditResult:
    """Result of post-answer citation marker verification (zero LLM cost)."""

    total_markers: int = 0
    valid: int = 0
    unresolved: int = 0


def audit_citation_markers(text: str, source_count: int) -> CitationAuditResult:
    """Extract fullwidth 【N】 markers and verify N is within [1, source_count]."""
    if source_count <= 0 or not text:
        return CitationAuditResult()

    markers = _CITATION_MARKER_RE.findall(text)
    if not markers:
        return CitationAuditResult()

    valid = 0
    unresolved = 0
    for num_str in markers:
        n = int(num_str)
        if 1 <= n <= source_count:
            valid += 1
        else:
            unresolved += 1

    return CitationAuditResult(total_markers=len(markers), valid=valid, unresolved=unresolved)


def resolve_source_count_for_audit(sources: list[dict[str, object]]) -> int:
    """Use list length and max assigned index so sparse numbering still audits correctly."""
    count = len(sources)
    for src in sources:
        idx = src.get("index")
        if isinstance(idx, int) and idx > count:
            count = idx
    return count
