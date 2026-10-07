"""Anti-overpromotion gate preventing single-occurrence observations from becoming stable preferences.

[INPUT]
- hashlib: sha256 for pattern fingerprinting
- dataclasses: dataclass
- datetime: datetime, timezone
- myrm_agent_harness.toolkits.memory.screen_observation.types: OverpromotionGateResult, PromotionStatus

[OUTPUT]
- AntiOverpromotionGate: Frequency & multi-session gatekeeper against ephemeral preference over-promotion

[POS]
Harness framework layer implementation of ChatGPT Desktop Skysight-style
anti-overpromotion gatekeeper ensuring only repeated, cross-session patterns become preferences.
Strict typing applied: No `any` types allowed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.screen_observation.types import (
    OverpromotionGateResult,
    PromotionStatus,
)


@dataclass
class ObservedPatternTracker:
    """Internal tracker recording occurrences and session lineage for a pattern fingerprint."""

    fingerprint: str
    first_seen: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_seen: datetime = field(default_factory=lambda: datetime.now(UTC))
    frequency_count: int = 0
    sessions_seen: set[str] = field(default_factory=set)


class AntiOverpromotionGate:
    """Gatekeeper enforcing that single-occurrence or ephemeral observations are kept

    as transient observation records and only promoted to stable preferences when verified
    across multiple distinct sessions.
    """

    def __init__(
        self,
        min_frequency_count: int = 2,
        min_distinct_sessions: int = 2,
    ) -> None:
        self.min_frequency_count = min_frequency_count
        self.min_distinct_sessions = min_distinct_sessions
        self._patterns: dict[str, ObservedPatternTracker] = {}

    def compute_fingerprint(self, statement: str) -> str:
        """Generate normalized SHA-256 fingerprint from statement for pattern deduplication."""
        normalized = " ".join(statement.lower().strip().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

    def evaluate(self, statement: str, session_id: str) -> OverpromotionGateResult:
        """Record observation occurrence and decide whether it qualifies for promotion to stable preference."""
        fingerprint = self.compute_fingerprint(statement)

        tracker = self._patterns.get(fingerprint)
        if tracker is None:
            tracker = ObservedPatternTracker(fingerprint=fingerprint)
            self._patterns[fingerprint] = tracker

        tracker.frequency_count += 1
        tracker.sessions_seen.add(session_id)
        tracker.last_seen = datetime.now(UTC)

        freq = tracker.frequency_count
        distinct_sessions = len(tracker.sessions_seen)

        if freq >= self.min_frequency_count and distinct_sessions >= self.min_distinct_sessions:
            status: PromotionStatus = "promoted_preference"
            is_promoted = True
            explanation = (
                f"Pattern verified across {distinct_sessions} distinct sessions "
                f"with {freq} occurrences; successfully promoted to stable preference."
            )
        elif freq >= 2 and distinct_sessions < self.min_distinct_sessions:
            status = "candidate_pattern"
            is_promoted = False
            explanation = (
                f"Observed {freq} times but isolated within a single session '{session_id}'; "
                f"held as candidate pattern to prevent over-promotion."
            )
        else:
            status = "transient_observation"
            is_promoted = False
            explanation = (
                "Single-occurrence observation; preserved as transient activity log "
                "to prevent over-generalizing incidental user actions."
            )

        return OverpromotionGateResult(
            status=status,
            frequency_count=freq,
            distinct_sessions_count=distinct_sessions,
            is_promoted=is_promoted,
            explanation=explanation,
            pattern_fingerprint=fingerprint,
        )

    def reset(self) -> None:
        """Clear recorded pattern states (useful for testing or cache eviction)."""
        self._patterns.clear()
