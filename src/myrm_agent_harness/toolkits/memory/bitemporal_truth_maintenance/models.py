"""Data models and immutable contracts for bitemporal truth maintenance.

[POS]
Defines mathematical half-open intervals, bitemporal coordinates, evidence records,
support dependency justification links, and truth maintenance snapshots.

[INPUT]
None (Standard library dataclasses, enum, typing)

[OUTPUT]
- TimeInterval
- BitemporalCoordinates
- EvidenceType
- EvidenceRecord
- SupportDependency
- TruthMaintenanceSnapshot
- TemporalQueryCriteria
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


@dataclass(frozen=True)
class TimeInterval:
    """Half-open time interval [start, end) representing a temporal range.

    If end is None, the interval is open-ended towards positive infinity [start, +inf).
    """

    start: float
    end: float | None = None

    def __post_init__(self) -> None:
        if self.end is not None and self.start > self.end:
            raise ValueError(
                f"Invalid interval: start ({self.start}) cannot exceed end ({self.end})"
            )

    @property
    def is_unbounded_end(self) -> bool:
        """Whether the interval extends infinitely into the future."""
        return self.end is None

    def contains(self, point: float) -> bool:
        """Tests whether point t lies within half-open interval [start, end)."""
        if point < self.start:
            return False
        return not (self.end is not None and point >= self.end)

    def overlaps(self, other: TimeInterval) -> bool:
        """Tests whether this interval overlaps with another interval."""
        self_end = float("inf") if self.end is None else self.end
        other_end = float("inf") if other.end is None else other.end
        return max(self.start, other.start) < min(self_end, other_end)


@dataclass(frozen=True)
class BitemporalCoordinates:
    """Bitemporal coordinate pair representing valid and known intervals.

    - valid_interval: [valid_at, valid_until) when the assertion is true in the real world.
    - known_interval: [known_at, retracted_at) when the system believed/recorded the assertion.
    """

    valid_interval: TimeInterval
    known_interval: TimeInterval

    def is_active_at(self, valid_time: float, known_time: float) -> bool:
        """Determines if the assertion is valid and currently known at the given coordinates."""
        return self.valid_interval.contains(valid_time) and self.known_interval.contains(
            known_time
        )


class EvidenceType(StrEnum):
    """Categorization of evidence nodes in the truth maintenance graph."""

    FACT = "fact"
    OBSERVATION = "observation"
    INFERENCE = "inference"
    DECISION = "decision"


@dataclass(frozen=True)
class BitemporalEvidenceRecord:
    """Atomic memory evidence record with bitemporal boundaries and confidence."""

    evidence_id: str
    content: str
    evidence_type: EvidenceType
    bitemporal: BitemporalCoordinates
    confidence: float = 1.0
    metadata: dict[str, str] = field(default_factory=dict)

    def is_retracted(self, as_of_known_time: float) -> bool:
        """Checks if the evidence was retracted at or before as_of_known_time."""
        known_end = self.bitemporal.known_interval.end
        if known_end is None:
            return False
        return as_of_known_time >= known_end

    def is_valid_and_known(self, valid_time: float, known_time: float) -> bool:
        """Checks whether this evidence holds at the specified bitemporal coordinate point."""
        return self.bitemporal.is_active_at(valid_time, known_time)


# Convenience alias for internal module usage
EvidenceRecord = BitemporalEvidenceRecord


@dataclass(frozen=True)
class SupportDependency:
    """Justification dependency linking an inference to its supporting premises."""

    inference_id: str
    premise_ids: tuple[str, ...]
    causal_distance: int = 1
    justification: str = ""

    def __post_init__(self) -> None:
        if self.causal_distance < 1:
            raise ValueError(
                f"causal_distance must be >= 1, got {self.causal_distance}"
            )


@dataclass(frozen=True)
class TruthMaintenanceSnapshot:
    """Read-only projected snapshot of active vs invalidated truth maintenance states."""

    active_evidences: tuple[BitemporalEvidenceRecord, ...]
    retracted_evidences: tuple[BitemporalEvidenceRecord, ...]
    active_inferences: tuple[BitemporalEvidenceRecord, ...]
    invalidated_inferences: tuple[BitemporalEvidenceRecord, ...]
    as_of_valid_time: float
    as_of_known_time: float

    @property
    def total_count(self) -> int:
        """Total number of evidence and inference records in this snapshot."""
        return (
            len(self.active_evidences)
            + len(self.retracted_evidences)
            + len(self.active_inferences)
            + len(self.invalidated_inferences)
        )


@dataclass(frozen=True)
class TemporalQueryCriteria:
    """Multi-criteria filter specification for as-of bitemporal queries."""

    as_of_valid_time: float | None = None
    as_of_known_time: float | None = None
    require_active_support: bool = True
    min_confidence: float = 0.0
    evidence_types: tuple[EvidenceType, ...] | None = None
