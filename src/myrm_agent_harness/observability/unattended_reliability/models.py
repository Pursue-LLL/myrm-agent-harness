"""[INPUT] Unattended agent run signals, recovery results, side-effect checks, and blocker verdicts.
[OUTPUT] Immutable data structures for the unattended reliability triad self-proof suite.
[POS] myrm_agent_harness.observability.unattended_reliability.models

Defines the core data models for measuring and proving unattended autonomous agent reliability:
1. Resume after restart success rate
2. Zero duplicate side-effects rate
3. Honest blocker reporting rate (never hallucinating success on failure)
"""

from dataclasses import dataclass, field
from enum import Enum
import time


class ResumeStatus(str, Enum):
    """Resume execution outcome after process or sandbox restart."""

    RESUMED_SUCCESS = "RESUMED_SUCCESS"
    RESUMED_FAILED = "RESUMED_FAILED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class SideEffectStatus(str, Enum):
    """Side effect idempotency verification status on retry/replay."""

    ZERO_DUPLICATE = "ZERO_DUPLICATE"
    DUPLICATE_DETECTED = "DUPLICATE_DETECTED"
    NO_SIDE_EFFECTS = "NO_SIDE_EFFECTS"


class FinalReportingStatus(str, Enum):
    """Veracity and honesty of the final run report."""

    GENUINE_SUCCESS = "GENUINE_SUCCESS"
    HONEST_BLOCKER = "HONEST_BLOCKER"
    HALLUCINATED_SUCCESS = "HALLUCINATED_SUCCESS"


@dataclass(frozen=True)
class RunReliabilityRecord:
    """Evaluation record of an unattended agent run across the triad dimensions."""

    run_id: str
    task_name: str
    resume_status: ResumeStatus
    side_effect_status: SideEffectStatus
    reporting_status: FinalReportingStatus
    detail: str = ""
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict[str, str | int]:
        return {
            "run_id": self.run_id,
            "task_name": self.task_name,
            "resume_status": self.resume_status.value,
            "side_effect_status": self.side_effect_status.value,
            "reporting_status": self.reporting_status.value,
            "detail": self.detail,
            "timestamp_ms": self.timestamp_ms,
        }


@dataclass(frozen=True)
class ReliabilityTriadScore:
    """Aggregated self-proof scoreboard for unattended reliability."""

    total_evaluated_runs: int
    resume_rate_pct: float
    zero_duplicate_side_effect_rate_pct: float
    honest_blocker_rate_pct: float
    composite_triad_score: float
    hallucinated_success_count: int
    duplicate_side_effect_count: int
    failed_resume_count: int
    recent_records: tuple[RunReliabilityRecord, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, float | int | list[dict[str, str | int]]]:
        return {
            "total_evaluated_runs": self.total_evaluated_runs,
            "resume_rate_pct": self.resume_rate_pct,
            "zero_duplicate_side_effect_rate_pct": self.zero_duplicate_side_effect_rate_pct,
            "honest_blocker_rate_pct": self.honest_blocker_rate_pct,
            "composite_triad_score": self.composite_triad_score,
            "hallucinated_success_count": self.hallucinated_success_count,
            "duplicate_side_effect_count": self.duplicate_side_effect_count,
            "failed_resume_count": self.failed_resume_count,
            "recent_records": [r.to_dict() for r in self.recent_records],
        }
