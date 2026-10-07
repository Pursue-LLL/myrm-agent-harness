"""Core implementation of Multi-Bot Shared Group Chatter Governor.

Provides continuous bot turn watchdog enforcement, pre-flight incremental cognitive value
introspection, turn mutex arbitration, and group emergency stop protection.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid

from .multibot_governor_types import (
    BotTurnEvent,
    CognitiveValueEvaluation,
    GovernorAction,
    GovernorDecision,
    MessageSenderRole,
    MultiBotGovernorConfig,
    MutexAcquireResult,
)

logger = logging.getLogger(__name__)

# Common non-substantive platitude patterns in bot-to-bot replies
_PLATITUDE_SUBSTRINGS: tuple[str, ...] = (
    "赞同",
    "完全赞同",
    "同意你的观点",
    "没有补充",
    "我没有补充了",
    "正如你所说",
    "说的很对",
    "好的，收到",
    "i agree",
    "agreed",
    "lgtm",
    "sounds good",
    "no further comment",
    "no additional comment",
    "well said",
)


class IncrementalCognitiveValueEvaluator:
    """Introspective gate evaluating whether a bot has substantive cognitive value to speak."""

    def evaluate(
        self,
        candidate_bot_id: str,
        event: BotTurnEvent,
    ) -> CognitiveValueEvaluation:
        """Evaluate whether a candidate bot should respond to the current group event."""
        # 1. Bot should never respond to its own monologue
        if event.sender_id == candidate_bot_id:
            return CognitiveValueEvaluation(
                should_respond=False,
                is_explicitly_mentioned=False,
                has_substantive_increment=False,
                reason="Candidate bot is the sender of the event.",
                action=GovernorAction.PASS,
            )

        # 2. Explicit mention or delegation gives high priority permission
        is_mentioned = (
            candidate_bot_id in event.mentioned_bot_ids
            or event.target_bot_id == candidate_bot_id
        )
        if is_mentioned:
            return CognitiveValueEvaluation(
                should_respond=True,
                is_explicitly_mentioned=True,
                has_substantive_increment=True,
                reason="Explicitly mentioned or targeted in group event.",
                action=GovernorAction.ALLOW,
            )

        # 3. Direct user messages warrant active processing
        if event.sender_role == MessageSenderRole.USER:
            return CognitiveValueEvaluation(
                should_respond=True,
                is_explicitly_mentioned=False,
                has_substantive_increment=True,
                reason="User prompt warrants assistance.",
                action=GovernorAction.ALLOW,
            )

        # 4. If previous message is from another bot, detect empty platitudes & ping-pong chatter
        content_lower = event.content.strip().lower()

        # Check for platitudes or zero-information echoes
        for platitude in _PLATITUDE_SUBSTRINGS:
            if platitude in content_lower and len(content_lower) < 80:
                return CognitiveValueEvaluation(
                    should_respond=False,
                    is_explicitly_mentioned=False,
                    has_substantive_increment=False,
                    reason=f"Detected polite platitude '{platitude}' without substantive increment.",
                    action=GovernorAction.PASS,
                )

        # If it is an unaddressed bot-to-bot statement without explicit delegation, suppress
        if not event.mentioned_bot_ids and event.target_bot_id is None:
            # When length is very short or just rhetorical question, pass
            if len(content_lower) < 25 or content_lower.endswith(("?", "？")):
                return CognitiveValueEvaluation(
                    should_respond=False,
                    is_explicitly_mentioned=False,
                    has_substantive_increment=False,
                    reason="Rhetorical question or open chatter between bots without direct target.",
                    action=GovernorAction.PASS,
                )

        return CognitiveValueEvaluation(
            should_respond=True,
            is_explicitly_mentioned=False,
            has_substantive_increment=True,
            reason="Substantive cognitive contribution permitted.",
            action=GovernorAction.ALLOW,
        )


class GroupTurnArbitrator:
    """Thread-safe turn mutex arbitrator preventing multiple bots from collision-answering."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active_leases: dict[str, tuple[str, str, float]] = {}  # group_id -> (bot_id, token_id, expires_at)

    def acquire(
        self,
        group_id: str,
        bot_id: str,
        lease_seconds: float = 30.0,
    ) -> MutexAcquireResult:
        """Attempt to acquire exclusive speaking rights for a given group chat."""
        with self._lock:
            now = time.time()
            current = self._active_leases.get(group_id)

            if current is not None:
                holder_id, token_id, expires_at = current
                if now < expires_at:
                    if holder_id == bot_id:
                        # Re-entrant acquisition / lease extension
                        new_expiry = now + lease_seconds
                        self._active_leases[group_id] = (bot_id, token_id, new_expiry)
                        return MutexAcquireResult(
                            acquired=True,
                            holder_bot_id=bot_id,
                            token_id=token_id,
                            expires_at=new_expiry,
                            reason="Lease extended by current holder.",
                        )
                    return MutexAcquireResult(
                        acquired=False,
                        holder_bot_id=holder_id,
                        token_id=None,
                        expires_at=expires_at,
                        reason=f"Turn mutex currently held by bot '{holder_id}'.",
                    )

            # Grant new lease
            new_token = f"mutex-{uuid.uuid4().hex[:12]}"
            new_expiry = now + lease_seconds
            self._active_leases[group_id] = (bot_id, new_token, new_expiry)
            return MutexAcquireResult(
                acquired=True,
                holder_bot_id=bot_id,
                token_id=new_token,
                expires_at=new_expiry,
                reason="Turn mutex acquired successfully.",
            )

    def release(self, group_id: str, bot_id: str, token_id: str) -> bool:
        """Release the acquired turn mutex lease."""
        with self._lock:
            current = self._active_leases.get(group_id)
            if current is None:
                return False
            holder_id, cur_token, _ = current
            if holder_id == bot_id and cur_token == token_id:
                del self._active_leases[group_id]
                return True
            return False


class MultiBotChatterGovernor:
    """Primary governor coordinating continuous bot watchdog, value gate, and emergency brake."""

    def __init__(
        self,
        config: MultiBotGovernorConfig | None = None,
        evaluator: IncrementalCognitiveValueEvaluator | None = None,
        arbitrator: GroupTurnArbitrator | None = None,
    ) -> None:
        self._config = config or MultiBotGovernorConfig()
        self._evaluator = evaluator or IncrementalCognitiveValueEvaluator()
        self._arbitrator = arbitrator or GroupTurnArbitrator()
        self._lock = threading.RLock()
        self._group_bot_turns: dict[str, int] = {}
        self._emergency_stopped_groups: set[str] = set()

    def record_event(self, group_id: str, event: BotTurnEvent) -> int:
        """Record a turn event in the group and update continuous turn counters."""
        with self._lock:
            if event.sender_role == MessageSenderRole.USER:
                # Human message breaks any bot-to-bot ping pong loop
                self._group_bot_turns[group_id] = 0
                self._emergency_stopped_groups.discard(group_id)
                return 0
            if event.sender_role == MessageSenderRole.BOT:
                current_turns = self._group_bot_turns.get(group_id, 0) + 1
                self._group_bot_turns[group_id] = current_turns
                return current_turns
            return self._group_bot_turns.get(group_id, 0)

    def evaluate_turn(
        self,
        group_id: str,
        candidate_bot_id: str,
        latest_event: BotTurnEvent,
    ) -> GovernorDecision:
        """Evaluate whether a candidate bot is authorized to speak in the group chat."""
        with self._lock:
            # 1. Emergency stop check
            if group_id in self._emergency_stopped_groups:
                return GovernorDecision(
                    action=GovernorAction.EMERGENCY_STOP,
                    should_respond=False,
                    continuous_bot_turns=self._group_bot_turns.get(group_id, 0),
                    reason="Group chat is currently in emergency stop state.",
                    notice_message="🛑 讨论已被人为终止，所有 AI 协程均已暂停。",
                )

            # 2. Continuous bot turn watchdog enforcement
            current_turns = self._group_bot_turns.get(group_id, 0)
            if (
                latest_event.sender_role == MessageSenderRole.BOT
                and current_turns >= self._config.max_continuous_bot_turns
            ):
                notice = self._config.circuit_break_notice_template.format(
                    turns=current_turns
                )
                logger.warning(
                    "MultiBotChatterGovernor tripped circuit break in group %s after %d bot turns",
                    group_id,
                    current_turns,
                )
                return GovernorDecision(
                    action=GovernorAction.CIRCUIT_BREAK,
                    should_respond=False,
                    continuous_bot_turns=current_turns,
                    reason=f"Exceeded max continuous bot turns ({self._config.max_continuous_bot_turns}).",
                    notice_message=notice,
                )

            # 3. Incremental cognitive value gate
            if self._config.enable_incremental_value_gate:
                eval_res = self._evaluator.evaluate(candidate_bot_id, latest_event)
                if not eval_res.should_respond:
                    return GovernorDecision(
                        action=GovernorAction.PASS,
                        should_respond=False,
                        continuous_bot_turns=current_turns,
                        reason=eval_res.reason,
                    )

            # 4. Turn mutex arbitration
            acquire_res = self._arbitrator.acquire(
                group_id=group_id,
                bot_id=candidate_bot_id,
                lease_seconds=self._config.mutex_lease_seconds,
            )
            if not acquire_res.acquired:
                return GovernorDecision(
                    action=GovernorAction.PASS,
                    should_respond=False,
                    continuous_bot_turns=current_turns,
                    reason=acquire_res.reason,
                )

            return GovernorDecision(
                action=GovernorAction.ALLOW,
                should_respond=True,
                continuous_bot_turns=current_turns,
                reason="Permitted to speak; turn mutex granted.",
                mutex_token_id=acquire_res.token_id,
            )

    def release_turn(self, group_id: str, bot_id: str, token_id: str) -> bool:
        """Release the acquired turn mutex when bot finishes turn."""
        return self._arbitrator.release(group_id, bot_id, token_id)

    def trigger_emergency_stop(self, group_id: str) -> None:
        """Trigger interactive emergency stop for the specified group chat."""
        with self._lock:
            self._emergency_stopped_groups.add(group_id)

    def reset_emergency_stop(self, group_id: str) -> None:
        """Reset emergency stop state for the group chat."""
        with self._lock:
            self._emergency_stopped_groups.discard(group_id)
            self._group_bot_turns[group_id] = 0

    def get_continuous_bot_turns(self, group_id: str) -> int:
        """Query active continuous bot turns for the group chat."""
        with self._lock:
            return self._group_bot_turns.get(group_id, 0)
