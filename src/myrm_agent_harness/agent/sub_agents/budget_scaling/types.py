"""Strongly-typed DTOs and constants for Subagent Concurrency & Tool Budget Adaptive Scaling (Item 31).

Defines legacy default recognition constants, new scaled defaults,
and migration/watermark contracts.

[INPUT]
- dataclasses
- datetime

[OUTPUT]
- LEGACY_DEFAULT_CONCURRENCY
- LEGACY_DEFAULT_MAX_TURNS
- DEFAULT_SCALED_CONCURRENCY
- DEFAULT_SCALED_MAX_TURNS
- DEFAULT_MAX_CHILDREN_PER_AGENT
- DEFAULT_MAX_DESCENDANTS_PER_RUN
- DEFAULT_WATERMARK_THRESHOLD_RATIO
- ConfigMigrationResult
- WatermarkAlert

[POS]
Strongly-typed DTOs and constants for Subagent Concurrency & Tool Budget Adaptive Scaling (Item 31).
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

# Legacy default values for subagent execution quotas
LEGACY_DEFAULT_CONCURRENCY = frozenset({3, 5})
LEGACY_DEFAULT_MAX_TURNS = frozenset({25, 50})

# Scaled production best-practice defaults (aligned with Hermes Agent v0.20.2)
DEFAULT_SCALED_CONCURRENCY: int = 10
DEFAULT_SCALED_MAX_TURNS: int = 250
DEFAULT_MAX_CHILDREN_PER_AGENT: int = 10
DEFAULT_MAX_DESCENDANTS_PER_RUN: int = 50

# Pre-warning alert threshold ratio for running subagent tasks
DEFAULT_WATERMARK_THRESHOLD_RATIO: float = 0.80


@dataclass(frozen=True)
class ConfigMigrationResult:
    """Audit report for zero-disruption subagent configuration migration."""

    migrated: bool
    old_concurrency: int | None
    new_concurrency: int
    old_max_turns: int | None
    new_max_turns: int
    concurrency_migrated: bool
    max_turns_migrated: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


@dataclass(frozen=True)
class WatermarkAlert:
    """Pre-warning heartbeat event emitted when a subagent approaches its turn limit."""

    task_id: str
    current_turn: int
    max_turns: int
    usage_ratio: float
    turns_remaining: int
    warning_message: str
    emitted_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
