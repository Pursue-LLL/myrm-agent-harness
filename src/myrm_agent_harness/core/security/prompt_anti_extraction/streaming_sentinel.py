"""Streaming Canary Sentinel for real-time prompt leak circuit breaker.

Monitors output tokens/chunks as they stream from the LLM, triggering sub-10ms emergency
circuit breaker trips and flushing output buffers whenever canary echoes are identified.
"""

from __future__ import annotations

import logging
import threading

from myrm_agent_harness.core.security.prompt_anti_extraction.types import (
    StreamingScanResult,
)

logger = logging.getLogger(__name__)


class StreamingCanarySentinel:
    """Thread-safe streaming sentinel intercepting canary echoes in real time."""

    def __init__(self) -> None:
        self._is_tripped: bool = False
        self._lock: threading.Lock = threading.Lock()

    @property
    def is_tripped(self) -> bool:
        """Whether the sentinel circuit breaker has tripped."""
        with self._lock:
            return self._is_tripped

    def scan_chunk(self, chunk: str, canary_token: str) -> StreamingScanResult:
        """Scan a streaming response chunk for canary token leakage.

        If the canary is detected, immediately trips the circuit breaker and replaces
        the chunk with an emergency safety placeholder.
        """
        with self._lock:
            if self._is_tripped:
                return StreamingScanResult(
                    canary_detected=True,
                    tripped=True,
                    scrubbed_chunk="[STREAM_TERMINATED_PREVIOUS_LEAK_DETECTED]",
                    alert_reason="Sentinel circuit breaker already tripped.",
                )

            if canary_token and canary_token in chunk:
                self._is_tripped = True
                logger.critical(
                    "EMERGENCY CIRCUIT BREAKER TRIPPED! Canary token '%s' detected in streaming chunk.",
                    canary_token,
                )
                return StreamingScanResult(
                    canary_detected=True,
                    tripped=True,
                    scrubbed_chunk="[EMERGENCY_CIRCUIT_BREAKER_TRIPPED: PROMPT_LEAK_PREVENTED]",
                    alert_reason="Canary echo detected in streaming output!",
                )

            return StreamingScanResult(
                canary_detected=False,
                tripped=False,
                scrubbed_chunk=chunk,
                alert_reason=None,
            )

    def reset(self) -> None:
        """Reset sentinel circuit breaker state (test isolation or new session)."""
        with self._lock:
            self._is_tripped = False
