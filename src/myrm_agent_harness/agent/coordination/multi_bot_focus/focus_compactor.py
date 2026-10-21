"""Multi-Bot Mention Focus Tracker and Anti-Thrash Context Compactor (Item 42).

[INPUT]
- Session ID, bot identifiers, viewport activity signals, turn indices,
  context token metrics, and streaming task card heartbeats.

[OUTPUT]
- Dynamic focused bot resolution for @mention, hysteresis-guarded compaction decisions,
  and abandoned streaming card cleanup.

[POS]
- Harness coordination layer engine for multi-agent desktop/web focus and memory stability.
"""

from __future__ import annotations

import dataclasses
import logging
from datetime import UTC, datetime

from .types import (
    BotFocusSnapshot,
    CompactionEvaluation,
    CompactionPolicy,
    StreamCardHeartbeat,
    StreamCardState,
)

logger = logging.getLogger(__name__)


class MultiBotFocusError(ValueError):
    """Raised when invalid operations or inputs occur in multi-bot focus management."""


class MultiBotFocusAndCompactionGuard:
    """Coordinates active viewport bot focus, anti-thrash compaction, and stream abandonment."""

    def __init__(self, default_policy: CompactionPolicy | None = None) -> None:
        self._policy = default_policy or CompactionPolicy()
        self._focus_snapshots: dict[str, dict[str, BotFocusSnapshot]] = {}
        self._last_compaction_turn: dict[str, int] = {}
        self._last_compaction_tokens: dict[str, int] = {}
        self._cards: dict[str, StreamCardHeartbeat] = {}

    # --- Part 1: Viewport Bot Focus for Mentions ---

    def update_bot_focus(
        self,
        session_id: str,
        bot_id: str,
        is_viewport_active: bool,
        turn_index: int,
    ) -> BotFocusSnapshot:
        """Update viewport presence and turn freshness for a bot to determine mention focus."""
        if not session_id.strip():
            msg = "Session ID cannot be empty."
            raise MultiBotFocusError(msg)
        if not bot_id.strip():
            msg = "Bot ID cannot be empty."
            raise MultiBotFocusError(msg)

        # Higher weight given to bots actively visible in viewport (+100.0)
        viewport_weight = 100.0 if is_viewport_active else 0.0
        focus_score = viewport_weight + (max(0, turn_index) * 1.0)

        snapshot = BotFocusSnapshot(
            bot_id=bot_id,
            is_viewport_active=is_viewport_active,
            last_active_turn=turn_index,
            focus_score=focus_score,
            updated_at=datetime.now(tz=UTC),
        )

        session_bots = self._focus_snapshots.setdefault(session_id, {})
        session_bots[bot_id] = snapshot
        logger.debug(
            "Updated bot focus for '%s' in session '%s': score=%.1f (viewport=%s)",
            bot_id,
            session_id,
            focus_score,
            is_viewport_active,
        )
        return snapshot

    def get_focused_bot(self, session_id: str) -> str | None:
        """Return the bot ID with the highest dynamic focus score in the session."""
        session_bots = self._focus_snapshots.get(session_id)
        if not session_bots:
            return None

        # Sort by focus_score descending, tie-break by updated_at
        sorted_bots = sorted(
            session_bots.values(),
            key=lambda b: (b.focus_score, b.updated_at),
            reverse=True,
        )
        return sorted_bots[0].bot_id

    def get_all_focus_snapshots(self, session_id: str) -> list[BotFocusSnapshot]:
        """Return all tracked bot focus snapshots in the given session."""
        session_bots = self._focus_snapshots.get(session_id, {})
        return list(session_bots.values())

    # --- Part 2: Anti-Thrash Context Compaction Guard ---

    def evaluate_compaction(
        self,
        session_id: str,
        current_tokens: int,
        max_context_tokens: int,
        current_turn: int,
        policy: CompactionPolicy | None = None,
    ) -> CompactionEvaluation:
        """Evaluate whether compaction should proceed or be suppressed by anti-thrash guard."""
        active_policy = policy or self._policy
        now = datetime.now(tz=UTC)

        if max_context_tokens <= 0:
            msg = "Max context tokens must be greater than zero."
            raise MultiBotFocusError(msg)

        trigger_threshold = int(max_context_tokens * active_policy.trigger_threshold_ratio)

        # Check 1: Token threshold
        if current_tokens < trigger_threshold:
            return CompactionEvaluation(
                should_compact=False,
                reason=f"Current tokens ({current_tokens}) below trigger threshold ({trigger_threshold})",
                current_tokens=current_tokens,
                max_context_tokens=max_context_tokens,
                cooldown_remaining=0,
                evaluated_at=now,
            )

        # Check 2: Cooldown turns
        last_turn = self._last_compaction_turn.get(session_id, -999)
        turns_since = current_turn - last_turn
        if turns_since < active_policy.cooldown_turns:
            cooldown_left = active_policy.cooldown_turns - turns_since
            return CompactionEvaluation(
                should_compact=False,
                reason=f"Compaction suppressed by cooldown: {cooldown_left} turns remaining",
                current_tokens=current_tokens,
                max_context_tokens=max_context_tokens,
                cooldown_remaining=cooldown_left,
                evaluated_at=now,
            )

        # Check 3: Token delta threshold since last compaction
        last_tokens = self._last_compaction_tokens.get(session_id, 0)
        token_delta = current_tokens - last_tokens
        if last_tokens > 0 and token_delta < active_policy.min_token_delta:
            return CompactionEvaluation(
                should_compact=False,
                reason=f"Token growth ({token_delta}) below minimum hysteresis delta ({active_policy.min_token_delta})",
                current_tokens=current_tokens,
                max_context_tokens=max_context_tokens,
                cooldown_remaining=0,
                evaluated_at=now,
            )

        return CompactionEvaluation(
            should_compact=True,
            reason="High-watermark exceeded and anti-thrash hysteresis clear",
            current_tokens=current_tokens,
            max_context_tokens=max_context_tokens,
            cooldown_remaining=0,
            evaluated_at=now,
        )

    def record_compaction_executed(
        self, session_id: str, executed_turn: int, tokens_after: int
    ) -> None:
        """Record timestamp and token watermark after compaction completes successfully."""
        self._last_compaction_turn[session_id] = executed_turn
        self._last_compaction_tokens[session_id] = tokens_after
        logger.info(
            "Compaction executed for session '%s' at turn %d (tokens after: %d)",
            session_id,
            executed_turn,
            tokens_after,
        )

    # --- Part 3: Streaming Card Abandonment Detection ---

    def record_card_heartbeat(
        self,
        card_id: str,
        session_id: str,
        bot_id: str,
        state: StreamCardState = StreamCardState.STREAMING,
    ) -> StreamCardHeartbeat:
        """Register or update heartbeat timestamp for an active task card stream."""
        heartbeat = StreamCardHeartbeat(
            card_id=card_id,
            session_id=session_id,
            bot_id=bot_id,
            state=state,
            last_heartbeat_at=datetime.now(tz=UTC),
        )
        self._cards[card_id] = heartbeat
        return heartbeat

    def detect_and_prune_abandoned_streams(
        self, session_id: str, timeout_seconds: float = 30.0
    ) -> list[str]:
        """Detect and transition dead streaming task cards to ABANDONED state."""
        now = datetime.now(tz=UTC)
        abandoned_ids: list[str] = []

        for card_id, card in list(self._cards.items()):
            if card.session_id != session_id:
                continue
            if card.state == StreamCardState.STREAMING:
                elapsed = (now - card.last_heartbeat_at).total_seconds()
                if elapsed >= timeout_seconds:
                    updated = dataclasses.replace(card, state=StreamCardState.ABANDONED)
                    self._cards[card_id] = updated
                    abandoned_ids.append(card_id)
                    logger.warning(
                        "Task card '%s' for bot '%s' abandoned after %.1fs silence",
                        card_id,
                        card.bot_id,
                        elapsed,
                    )

        return abandoned_ids

    def get_card(self, card_id: str) -> StreamCardHeartbeat | None:
        """Retrieve task card heartbeat record by card ID."""
        return self._cards.get(card_id)

    def mark_card_completed(self, card_id: str) -> bool:
        """Mark task card stream as completed cleanly."""
        card = self._cards.get(card_id)
        if card is None:
            return False
        self._cards[card_id] = dataclasses.replace(
            card, state=StreamCardState.COMPLETED, last_heartbeat_at=datetime.now(tz=UTC)
        )
        return True
