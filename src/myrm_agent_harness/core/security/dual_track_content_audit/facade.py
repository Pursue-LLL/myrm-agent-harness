
from .mirror_conduit import AsyncMirrorConduit, StreamCircuitBreaker
from .scanner import OutBandContentScanner
from .types import (
    AuditVerdict,
    CircuitBreakerSignal,
    DualTrackMetrics,
)


class DualTrackContentAuditSuite:
    """Unified facade for decoupled out-of-band content auditing and realtime stream circuit-breaking."""

    def __init__(self) -> None:
        self.scanner = OutBandContentScanner()
        self.breaker = StreamCircuitBreaker()
        self.conduit = AsyncMirrorConduit(scanner=self.scanner, breaker=self.breaker)

    def mirror_chunk(
        self,
        session_id: str,
        text_chunk: str,
        sequence_no: int,
        is_final: bool = False,
    ) -> tuple[AuditVerdict, CircuitBreakerSignal | None]:
        """Mirror streaming chunk out-of-band and obtain verdict and optional breaker signal."""
        return self.conduit.mirror_and_audit_chunk(
            session_id=session_id,
            text_chunk=text_chunk,
            sequence_no=sequence_no,
            is_final=is_final,
        )

    def scan_full_text(self, text: str) -> AuditVerdict:
        """Perform direct synchronous text compliance scan."""
        return self.scanner.scan_text(text)

    def is_session_tripped(self, session_id: str) -> bool:
        """Check if streaming session is halted by circuit breaker."""
        return self.breaker.is_tripped(session_id)

    def get_breaker_signal(self, session_id: str) -> CircuitBreakerSignal | None:
        """Retrieve tripping details for a session."""
        return self.breaker.get_trip_signal(session_id)

    def reset_breaker(self, session_id: str) -> bool:
        """Reset circuit breaker for a session."""
        return self.breaker.reset(session_id)

    def get_metrics(self) -> DualTrackMetrics:
        """Retrieve telemetry metrics."""
        return self.conduit.get_metrics()
