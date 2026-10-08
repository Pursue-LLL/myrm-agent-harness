"""Type definitions for memory retrieval post-fetch injection screening suite.

Strict typing rules applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ScreeningPathMode(StrEnum):
    """Execution pathway chosen by the dual-path screening gate."""

    JEV_AND_LOCAL = "jev+local"
    LOCAL_ONLY = "local-only"
    NONE = "none"


class PassageVerdictStatus(StrEnum):
    """Verdict classification for a single memory passage."""

    CLEAN = "clean"
    TOXIC = "toxic"
    FAIL_OPEN = "fail_open"


@dataclass(frozen=True)
class MemoryPassageUnit:
    """Represents a discrete memory passage retrieved from vector/long-term storage."""

    passage_id: str
    content: str
    source_uri: str = ""
    relevance_score: float = 0.0
    created_at: str = ""


@dataclass(frozen=True)
class PatternMatchDetail:
    """Details of a localized pattern match."""

    pattern_category: str
    matched_substring: str
    risk_level: str  # "high", "critical", "medium"


@dataclass
class PassageScreeningVerdict:
    """Screening verdict evaluation for a single memory passage."""

    passage_id: str
    status: PassageVerdictStatus
    confidence_score: float
    pathway: ScreeningPathMode
    matched_patterns: list[PatternMatchDetail] = field(default_factory=list)
    rejection_reason: str = ""


@dataclass(frozen=True)
class MemoryScreeningPolicy:
    """Configuration governing the memory post-fetch screening gate."""

    threshold: float = 0.5
    remote_timeout_seconds: float = 3.5
    remote_scorer_enabled: bool = True
    quarantine_toxic_passages: bool = True
    enable_url_exfiltration_scan: bool = True
    enable_command_risk_scan: bool = True


@dataclass
class QuarantinedPassageReport:
    """Structured audit report for an isolated toxic passage."""

    passage_id: str
    source_uri: str
    snippet: str
    rejection_reason: str
    pathway_used: ScreeningPathMode
    threat_category: str
    detected_at: str


@dataclass
class MemoryScreeningBatchResult:
    """Consolidated outcome of memory passage batch screening."""

    total_evaluated: int
    clean_passages: list[MemoryPassageUnit]
    quarantined_reports: list[QuarantinedPassageReport]
    pathway_taken: ScreeningPathMode
    latency_ms: float
    degradation_reason: str = ""
