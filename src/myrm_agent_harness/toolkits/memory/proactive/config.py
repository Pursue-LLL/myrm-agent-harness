"""Commitment extraction and delivery configuration.

[INPUT]
- (none)

[OUTPUT]
- CommitmentConfig: Tunable parameters for extraction thresholds and delivery limits.

[POS]
Configuration dataclass for the commitment tracking system. Controls
extraction confidence thresholds, delivery rate limits, and expiration.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommitmentConfig:
    """Tunable parameters for commitment tracking."""

    enabled: bool = True

    confidence_threshold: float = 0.65
    care_confidence_threshold: float = 0.86

    max_per_day: int = 3
    max_per_heartbeat: int = 3
    expire_after_hours: int = 72

    debounce_turns: int = 3
    """Minimum conversation turns before extraction triggers."""
