"""Data models and type definitions for explicit memory error contracts and zero-hallucination defense.

[POS]
src/myrm_agent_harness/toolkits/memory/zero_hallucination/models.py
Defines strongly-typed retrieval state assertions, error severities, and defensive result contracts
to completely prevent silent error-swallowing and model memory fabrication.

[INPUT]
- enum: StrEnum
- dataclasses: dataclass, field
- typing: Optional, List

[OUTPUT]
- MemoryRetrievalState: Tri-state status enumeration (FOUND, EXPLICIT_EMPTY, SERVICE_UNAVAILABLE, PARTIAL_DEGRADED, SEARCH_FAILED)
- RetrievalErrorSeverity: Error severity level (TRANSIENT, FATAL, DEGRADED)
- MemoryFactItem: Single retrieved factual statement with metadata
- ZeroHallucinationRetrievalResult: Full defensive query result contract
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class MemoryRetrievalState(StrEnum):
    """Explicit tri-state assertion for memory retrieval outcomes."""

    FOUND = "found"
    EXPLICIT_EMPTY = "explicit_empty"
    SERVICE_UNAVAILABLE = "service_unavailable"
    PARTIAL_DEGRADED = "partial_degraded"
    SEARCH_FAILED = "search_failed"


class RetrievalErrorSeverity(StrEnum):
    """Severity classification for retrieval subsystem faults."""

    TRANSIENT = "transient"
    FATAL = "fatal"
    DEGRADED = "degraded"


@dataclass(frozen=True)
class MemoryFactItem:
    """Individual factual statement or preference retrieved from memory store."""

    id: str
    text: str
    category: str = "preference"
    score: float = 1.0


@dataclass(frozen=True)
class ZeroHallucinationRetrievalResult:
    """Strictly-typed retrieval outcome carrying defensive anti-hallucination directives."""

    state: MemoryRetrievalState
    query: str
    facts: list[MemoryFactItem] = field(default_factory=list)
    total_matched: int = 0
    error_code: str | None = None
    error_message: str | None = None
    degraded_sources: list[str] = field(default_factory=list)
    guard_instruction: str = ""
