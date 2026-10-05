"""Domain models for Workspace Living Governance (ADRs and Known Issues).

[INPUT]
- None (pure domain models)

[OUTPUT]
- KnownIssueEntry: Structured entry representing an environmental pitfall or bug workaround
- ADRMetadata: Structured representation of an Architecture Decision Record
- CausalDeduplicationReport: Result of idempotent Known Issue merging

[POS]
Domain contract layer for workspace living documentation synchronization.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

_TIMESTAMP_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b"
)
_HEX_ADDR_RE = re.compile(r"\b0x[0-9a-fA-F]+\b")
_UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b")
_PID_RE = re.compile(r"\bpid\s*[:=]?\s*\d+\b", re.IGNORECASE)


def _normalize_causal_text(text: str) -> str:
    """Strip dynamic runtime artifacts (timestamps, pointers, UUIDs) for stable fingerprinting."""
    cleaned = _TIMESTAMP_RE.sub("<TIMESTAMP>", text)
    cleaned = _HEX_ADDR_RE.sub("<ADDR>", cleaned)
    cleaned = _UUID_RE.sub("<UUID>", cleaned)
    cleaned = _PID_RE.sub("pid <PID>", cleaned)
    return re.sub(r"\s+", " ", cleaned.strip().lower())


def compute_error_signature(symptom: str, trigger_condition: str) -> str:
    """Compute normalized SHA-256 fingerprint from symptom and trigger condition."""
    normalized_symptom = _normalize_causal_text(symptom)
    normalized_trigger = _normalize_causal_text(trigger_condition)
    combined = f"{normalized_symptom}::{normalized_trigger}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class KnownIssueEntry:
    """Structured entry in KNOWN_ISSUES.md documenting an environment quirk or workaround."""

    id: str
    title: str
    symptom: str
    trigger_condition: str
    workaround: str
    error_signature: str = ""
    occurred_count: int = 1
    first_seen: str = field(default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%d"))
    last_seen: str = field(default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%d"))

    def __post_init__(self) -> None:
        if not self.error_signature:
            object.__setattr__(
                self,
                "error_signature",
                compute_error_signature(self.symptom, self.trigger_condition),
            )

    def to_markdown(self) -> str:
        """Format entry as a human-readable and machine-parseable Markdown block."""
        return (
            f"### [{self.id}] {self.title}\n"
            f"<!-- signature: {self.error_signature} | occurrences: {self.occurred_count} -->\n"
            f"- **现象 (Symptom)**: {self.symptom}\n"
            f"- **触发条件 (Trigger)**: {self.trigger_condition}\n"
            f"- **避坑对策 (Workaround)**: {self.workaround}\n"
            f"- **记录时间 (Timeline)**: {self.first_seen} ~ {self.last_seen}\n"
        )


@dataclass(frozen=True, slots=True)
class ADRMetadata:
    """Structured representation of an Architectural Decision Record."""

    id: str
    title: str
    status: str
    context: str
    decision: str
    date: str = field(default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%d"))
    consequences: str = ""

    def to_markdown(self) -> str:
        """Format as MADR (Markdown Architectural Decision Record) standard."""
        return (
            f"# {self.id}: {self.title}\n\n"
            f"* Status: {self.status}\n"
            f"* Date: {self.date}\n\n"
            f"## Context and Problem Statement\n\n{self.context}\n\n"
            f"## Decision Outcome\n\n{self.decision}\n\n"
            f"## Consequences\n\n{self.consequences if self.consequences else 'Positive impact on architecture.'}\n"
        )


@dataclass(frozen=True, slots=True)
class CausalDeduplicationReport:
    """Result of appending or reconciling an issue into KNOWN_ISSUES.md."""

    added: bool
    updated: bool
    issue_id: str
    error_signature: str
    file_path: str
