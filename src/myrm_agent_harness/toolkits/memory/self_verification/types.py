"""Typed data contracts for the self verification subsystem.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- VerificationHealthGrade: Health grade for memory verification diagnostics.
- FactMutationProbeResult: Outcome of in-place fact mutation & contradiction elimination probe.
- ZeroLexicalOverlapProbeResult: Outcome of pure semantic recall probe with zero lexical overlap.
- ProceduralAntiDropProbeResult: Outcome of procedural rule routing & anti-silent drop probe.
- MemoryVerificationReport: Comprehensive diagnostic benchmark report with sandbox rollback confirmation.

[POS]
Typed data contracts for the self verification subsystem.
"""

from dataclasses import dataclass
from enum import StrEnum


class VerificationHealthGrade(StrEnum):
    """Health grade for memory verification diagnostics."""

    EXCELLENT = "excellent"
    GOOD = "good"
    DEGRADED = "degraded"
    CRITICAL = "critical"


@dataclass(frozen=True)
class FactMutationProbeResult:
    """Outcome of in-place fact mutation & contradiction elimination probe."""

    probe_id: str
    entity_key: str
    initial_fact: str
    updated_fact: str
    success: bool
    retained_fact_count: int
    is_latest_retained: bool
    residual_conflict_count: int
    latency_ms: float
    details: str


@dataclass(frozen=True)
class ZeroLexicalOverlapProbeResult:
    """Outcome of pure semantic recall probe with zero lexical overlap."""

    probe_id: str
    query: str
    memory_text: str
    lexical_overlap_ratio: float
    is_zero_overlap: bool
    cosine_similarity: float
    recalled: bool
    latency_ms: float
    details: str


@dataclass(frozen=True)
class ProceduralAntiDropProbeResult:
    """Outcome of procedural rule routing & anti-silent drop probe."""

    probe_id: str
    rule_content: str
    routed_track: str
    was_dropped: bool
    is_preserved: bool
    drop_reason: str | None
    latency_ms: float
    details: str


@dataclass(frozen=True)
class MemoryVerificationReport:
    """Comprehensive diagnostic benchmark report with sandbox rollback confirmation."""

    report_id: str
    sandbox_namespace: str
    grade: VerificationHealthGrade
    total_probes: int
    passed_probes: int
    score: float
    sandbox_cleaned: bool
    fact_mutation_result: FactMutationProbeResult
    zero_lexical_result: ZeroLexicalOverlapProbeResult
    procedural_anti_drop_result: ProceduralAntiDropProbeResult
    mean_latency_ms: float
    summary: str
