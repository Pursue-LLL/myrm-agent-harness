import threading
import time

from .scanner import OutBandContentScanner
from .types import (
    AuditVerdict,
    CircuitBreakerActionEnum,
    CircuitBreakerSignal,
    ContentRiskLevelEnum,
    DualTrackMetrics,
    ViolationCategoryEnum,
)


class StreamCircuitBreaker:
    """Realtime stream circuit breaker tripping sessions upon critical violations."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tripped: dict[str, CircuitBreakerSignal] = {}

    def is_tripped(self, session_id: str) -> bool:
        """Check if streaming session has been interrupted by circuit breaker."""
        with self._lock:
            return session_id in self._tripped

    def get_trip_signal(self, session_id: str) -> CircuitBreakerSignal | None:
        """Retrieve the circuit breaking signal for a session."""
        with self._lock:
            return self._tripped.get(session_id)

    def trip(
        self,
        session_id: str,
        trigger_sequence_no: int,
        category: ViolationCategoryEnum,
        reason: str,
    ) -> CircuitBreakerSignal:
        """Trip circuit breaker and generate abort frame."""
        abort_frame = (
            f"\n\n[STREAM_ABORT_SAFETY_VIOLATION: {category.value} - {reason}]\n"
        )
        signal = CircuitBreakerSignal(
            session_id=session_id,
            trigger_sequence_no=trigger_sequence_no,
            action=CircuitBreakerActionEnum.TRIP_AND_ABORT,
            category=category,
            abort_frame=abort_frame,
            reason=reason,
            timestamp=time.time(),
        )
        with self._lock:
            self._tripped[session_id] = signal
        return signal

    def reset(self, session_id: str) -> bool:
        """Reset tripped circuit breaker state for a session."""
        with self._lock:
            if session_id in self._tripped:
                del self._tripped[session_id]
                return True
            return False

    @property
    def total_tripped(self) -> int:
        """Total count of tripped breakers."""
        with self._lock:
            return len(self._tripped)


class AsyncMirrorConduit:
    """Decoupled out-of-band streaming mirror conduit and compliance evaluator."""

    def __init__(self, scanner: OutBandContentScanner, breaker: StreamCircuitBreaker) -> None:
        self._scanner = scanner
        self._breaker = breaker
        self._lock = threading.Lock()
        self._session_buffers: dict[str, str] = {}
        self._total_chunks: int = 0
        self._total_violations: int = 0

    def mirror_and_audit_chunk(
        self,
        session_id: str,
        text_chunk: str,
        sequence_no: int,
        is_final: bool = False,
    ) -> tuple[AuditVerdict, CircuitBreakerSignal | None]:
        """Asynchronously mirror chunk to out-of-band audit and evaluate circuit breaking."""
        # Check if already tripped
        if self._breaker.is_tripped(session_id):
            existing_signal = self._breaker.get_trip_signal(session_id)
            verdict = AuditVerdict(
                is_violation=True,
                risk_level=ContentRiskLevelEnum.CRITICAL,
                category=existing_signal.category if existing_signal else ViolationCategoryEnum.NONE,
                confidence=1.0,
                matched_pattern=None,
                reason="Session stream already halted by safety circuit breaker.",
            )
            return verdict, existing_signal

        with self._lock:
            self._total_chunks += 1
            current_buffer = self._session_buffers.get(session_id, "")
            updated_buffer = current_buffer + text_chunk
            # Keep rolling window of last 2000 chars to prevent unbounded memory growth
            if len(updated_buffer) > 2000:
                self._session_buffers[session_id] = updated_buffer[-2000:]
            else:
                self._session_buffers[session_id] = updated_buffer

            inspect_text = self._session_buffers[session_id]

            if is_final:
                # Cleanup session buffer on final chunk
                self._session_buffers.pop(session_id, None)

        # Scan the text window
        verdict = self._scanner.scan_text(inspect_text)

        signal: CircuitBreakerSignal | None = None
        if verdict.is_violation and verdict.risk_level == ContentRiskLevelEnum.CRITICAL:
            with self._lock:
                self._total_violations += 1
            signal = self._breaker.trip(
                session_id=session_id,
                trigger_sequence_no=sequence_no,
                category=verdict.category,
                reason=verdict.reason,
            )

        return verdict, signal

    def get_metrics(self) -> DualTrackMetrics:
        """Retrieve telemetry metrics for the mirror conduit."""
        with self._lock:
            active_sessions = len(self._session_buffers)
            total_chunks = self._total_chunks
            total_violations = self._total_violations

        return DualTrackMetrics(
            total_chunks_mirrored=total_chunks,
            total_violations_detected=total_violations,
            total_breakers_tripped=self._breaker.total_tripped,
            active_monitored_sessions=active_sessions,
        )
