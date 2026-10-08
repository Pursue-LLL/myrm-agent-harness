from dataclasses import dataclass, field
from enum import StrEnum


class ContentRiskLevelEnum(StrEnum):
    """Risk severity classification for audited content."""

    SAFE = "SAFE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    CRITICAL = "CRITICAL"


class ViolationCategoryEnum(StrEnum):
    """Categorization of detected content safety violations."""

    NONE = "NONE"
    POLITICAL_SENSITIVE = "POLITICAL_SENSITIVE"
    TRADE_SECRET = "TRADE_SECRET"
    CREDENTIAL_LEAK = "CREDENTIAL_LEAK"
    PROMPT_INJECTION = "PROMPT_INJECTION"
    FINANCIAL_CONFIDENTIAL = "FINANCIAL_CONFIDENTIAL"


class CircuitBreakerActionEnum(StrEnum):
    """Action instructed by the circuit breaker on a streaming session."""

    PASS = "PASS"
    TRIP_AND_ABORT = "TRIP_AND_ABORT"
    WARN = "WARN"


@dataclass(frozen=True)
class AuditChunk:
    """A streaming text chunk mirrored for out-of-band compliance scanning."""

    session_id: str
    sequence_no: int
    text: str
    is_final: bool
    timestamp: float
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AuditVerdict:
    """Inspection verdict returned by the out-of-band audit engine."""

    is_violation: bool
    risk_level: ContentRiskLevelEnum
    category: ViolationCategoryEnum
    confidence: float
    matched_pattern: str | None
    reason: str


@dataclass(frozen=True)
class CircuitBreakerSignal:
    """Interruption frame injected into the streaming channel upon critical violation."""

    session_id: str
    trigger_sequence_no: int
    action: CircuitBreakerActionEnum
    category: ViolationCategoryEnum
    abort_frame: str
    reason: str
    timestamp: float


@dataclass(frozen=True)
class DualTrackMetrics:
    """Telemetry counters for dual-track audit and circuit breaking."""

    total_chunks_mirrored: int
    total_violations_detected: int
    total_breakers_tripped: int
    active_monitored_sessions: int
