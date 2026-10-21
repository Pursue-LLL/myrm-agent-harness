"""Domain types and contracts for Multi-Bot Mention Focus & Anti-Thrash Compaction (Item 42).

[INPUT]
- Viewport focus events, active bot telemetry, context token counts,
  and stream task card heartbeats.

[OUTPUT]
- Strongly-typed models for BotFocusSnapshot, CompactionPolicy,
  CompactionEvaluation, StreamCardState, and StreamCardHeartbeat.

[POS]
- Harness coordination layer contracts for multi-bot mention follow and anti-thrash compaction.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import UTC, datetime


class StreamCardState(enum.StrEnum):
    """Lifecycle state of a streaming multi-bot task progress card."""

    STREAMING = "streaming"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    FAILED = "failed"


@dataclass(frozen=True)
class BotFocusSnapshot:
    """Snapshot representing the focus score and viewport activity of a bot in a session."""

    bot_id: str
    is_viewport_active: bool
    last_active_turn: int
    focus_score: float
    updated_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


@dataclass(frozen=True)
class CompactionPolicy:
    """Anti-thrash hysteresis and cooldown thresholds for context compaction."""

    trigger_threshold_ratio: float = 0.90
    target_threshold_ratio: float = 0.75
    cooldown_turns: int = 3
    min_token_delta: int = 500


@dataclass(frozen=True)
class CompactionEvaluation:
    """Result of an anti-thrash compaction check preventing high-frequency churn."""

    should_compact: bool
    reason: str
    current_tokens: int
    max_context_tokens: int
    cooldown_remaining: int
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


@dataclass(frozen=True)
class StreamCardHeartbeat:
    """Heartbeat telemetry for streaming multi-bot task cards preventing zombie states."""

    card_id: str
    session_id: str
    bot_id: str
    state: StreamCardState = StreamCardState.STREAMING
    last_heartbeat_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
