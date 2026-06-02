"""Privacy Tracker — per-turn sensitivity level tracking.

Tracks the privacy classification (S1/S2/S3) for the current Agent turn,
following the same ContextVar session-scoped pattern as audit.py and
taint_tracker.py.

Per-turn semantics: ``currentTurnLevel`` is reset at the start of each
turn via ``reset_turn()``. ``highestLevel`` accumulates across all turns
for audit purposes.

[INPUT]

[OUTPUT]
- PrivacyTracker: per-turn + cumulative sensitivity tracking
- set_privacy_policy() / get_privacy_policy(): ContextVar-based privacy policy access
- get_privacy_tracker() / reset_privacy_tracker(): ContextVar accessors
- get_pending_privacy_event(): drain consume-once SSE event for stream executor

[POS]
Per-turn privacy state tracker. ContextVar session-scoped, independently evaluates each turn for privacy-sensitive content.

"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass, field

from myrm_agent_harness.core.security.types import PrivacyPolicy, SensitivityLevel

logger = logging.getLogger(__name__)

_privacy_policy_var: ContextVar[PrivacyPolicy | None] = ContextVar(
    "core_privacy_policy", default=None
)


def set_privacy_policy(policy: PrivacyPolicy | None) -> None:
    """Set the active PrivacyPolicy for the current async context.

    Called by the agent middleware when setting up SecurityConfig.
    """
    _privacy_policy_var.set(policy)


def get_privacy_policy() -> PrivacyPolicy:
    """Get the active PrivacyPolicy for the current async context."""
    policy = _privacy_policy_var.get()
    return policy if policy is not None else PrivacyPolicy()


_LEVEL_ORDER: dict[SensitivityLevel, int] = {
    SensitivityLevel.S1: 1,
    SensitivityLevel.S2: 2,
    SensitivityLevel.S3: 3,
}


def _higher_level(a: SensitivityLevel, b: SensitivityLevel) -> SensitivityLevel:
    return a if _LEVEL_ORDER[a] >= _LEVEL_ORDER[b] else b


@dataclass
class DetectionRecord:
    """A single PII detection event within a turn."""

    level: SensitivityLevel
    checkpoint: str
    patterns: list[str] = field(default_factory=list)


class PrivacyTracker:
    """Tracks privacy classification for the current Agent session.

    ``current_turn_level`` reflects the highest sensitivity detected in
    the current turn and is reset at each new turn.
    ``highest_level`` never decreases — it records the all-time maximum
    for audit and statistics.
    ``_pending_event`` allows the stream executor to drain privacy events
    without polling repeatedly.
    """

    __slots__ = (
        "_current_turn_level",
        "_highest_level",
        "_pending_event",
        "_pending_route_event",
        "_route_label",
        "_turn_detections",
    )

    def __init__(self) -> None:
        self._current_turn_level: SensitivityLevel = SensitivityLevel.S1
        self._highest_level: SensitivityLevel = SensitivityLevel.S1
        self._turn_detections: list[DetectionRecord] = []
        self._pending_event: bool = False
        self._route_label: str | None = None
        self._pending_route_event: bool = False

    def record(
        self,
        level: SensitivityLevel,
        checkpoint: str,
        patterns: list[str] | None = None,
    ) -> None:
        """Record a PII detection event, updating both turn and cumulative levels."""
        self._current_turn_level = _higher_level(self._current_turn_level, level)
        self._highest_level = _higher_level(self._highest_level, level)
        self._turn_detections.append(
            DetectionRecord(level=level, checkpoint=checkpoint, patterns=patterns or [])
        )
        if level != SensitivityLevel.S1:
            self._pending_event = True
            logger.warning(
                "[PRIVACY] level=%s checkpoint=%s patterns=%s",
                level.value,
                checkpoint,
                ",".join(patterns or []),
            )

    def reset_turn(self) -> None:
        """Reset per-turn state. Call at the start of each new user turn."""
        self._current_turn_level = SensitivityLevel.S1
        self._turn_detections.clear()
        self._route_label = None
        self._pending_route_event = False

    @property
    def current_turn_level(self) -> SensitivityLevel:
        return self._current_turn_level

    @property
    def highest_level(self) -> SensitivityLevel:
        return self._highest_level

    @property
    def is_private(self) -> bool:
        return self._current_turn_level != SensitivityLevel.S1

    @property
    def turn_detections(self) -> list[DetectionRecord]:
        return list(self._turn_detections)

    def drain_pending_event(self) -> dict[str, str] | None:
        """Return a privacy event dict if PII was detected, then clear the flag.

        Returns None if no new PII was detected since the last drain.
        This is a consume-once pattern: the stream executor calls this
        each iteration to emit SSE events without redundant polling.
        """
        if not self._pending_event:
            return None
        self._pending_event = False

        policy = get_privacy_policy()
        action = (
            policy.s3_action.value
            if self._current_turn_level == SensitivityLevel.S3
            else policy.s2_action.value
        )
        return {
            "current_turn_level": self._current_turn_level.value,
            "highest_level": self._highest_level.value,
            "action": action,
        }

    def record_route(self, route_label: str) -> None:
        """Record the privacy routing decision for this turn."""
        self._route_label = route_label
        self._pending_route_event = True

    @property
    def route_label(self) -> str | None:
        return self._route_label

    def drain_pending_route_event(self) -> dict[str, str] | None:
        """Return a route event dict if a routing decision was made, then clear.

        Same consume-once pattern as ``drain_pending_event``.
        """
        if not self._pending_route_event:
            return None
        self._pending_route_event = False
        return {
            "route": self._route_label or "unknown",
            "level": self._current_turn_level.value,
        }


_privacy_tracker_var: ContextVar[PrivacyTracker] = ContextVar("privacy_tracker")


def get_privacy_tracker() -> PrivacyTracker:
    """Get the PrivacyTracker for the current async context.

    Creates a new one if none exists (lazy initialization).
    """
    try:
        return _privacy_tracker_var.get()
    except LookupError:
        tracker = PrivacyTracker()
        _privacy_tracker_var.set(tracker)
        return tracker


def reset_privacy_tracker() -> None:
    """Reset privacy tracker state. Call at the start of each Agent run."""
    _privacy_tracker_var.set(PrivacyTracker())


def get_pending_privacy_event() -> dict[str, str] | None:
    """Drain the pending privacy event from the current context, if any.

    Returns a dict suitable for SSE emission, or None if no new PII was
    detected. Safe to call even when no tracker exists.
    """
    try:
        tracker = _privacy_tracker_var.get()
    except LookupError:
        return None
    return tracker.drain_pending_event()


def get_pending_route_event() -> dict[str, str] | None:
    """Drain the pending route event from the current context, if any.

    Returns a dict suitable for SSE emission, or None if no routing
    decision was made. Safe to call even when no tracker exists.
    """
    try:
        tracker = _privacy_tracker_var.get()
    except LookupError:
        return None
    return tracker.drain_pending_route_event()
