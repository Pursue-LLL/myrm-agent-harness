"""Coordination and lifecycle management for Time-Traveling Stream Rules (TTSR).

Coordinates sliding-window regex matching, repeat-gap quiet cooldown periods,
bounded retry breaker limits (max_retries=2), and compaction-immune injection formatting.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from langchain_core.messages import HumanMessage

from myrm_agent_harness.agent.context_management.working_memory.marks import (
    WorkingMemoryMark,
    with_message_marks,
)
from myrm_agent_harness.agent.streaming.rules.matcher import TtsrMatcher
from myrm_agent_harness.agent.streaming.rules.types import (
    RuleTarget,
    StreamRule,
    TtsrMatchResult,
)
from myrm_agent_harness.toolkits.code_execution.executors.models import (
    scrub_sensitive_info,
)

logger = logging.getLogger(__name__)


class TtsrCoordinator:
    """Manages active stream rules, triggers interruptions, and tracks cooldowns."""

    def __init__(
        self,
        rules: Sequence[StreamRule] | None = None,
        max_retries: int = 2,
        window_size: int = 128,
    ) -> None:
        self._rules: list[StreamRule] = list(rules or [])
        self._max_retries: int = max(0, max_retries)
        self._matcher: TtsrMatcher = TtsrMatcher(window_size=window_size)
        self._rule_last_triggered_turn: dict[str, int] = {}
        self._retries_this_turn: int = 0
        self._interrupt_requested: bool = False
        self._last_match: TtsrMatchResult | None = None

    @property
    def rules(self) -> list[StreamRule]:
        return list(self._rules)

    @property
    def max_retries(self) -> int:
        return self._max_retries

    @property
    def retries_this_turn(self) -> int:
        return self._retries_this_turn

    @property
    def interrupt_requested(self) -> bool:
        return self._interrupt_requested

    @property
    def last_match(self) -> TtsrMatchResult | None:
        return self._last_match

    def register_rule(self, rule: StreamRule) -> None:
        """Register or replace a rule by its rule_id."""
        self._rules = [r for r in self._rules if r.rule_id != rule.rule_id]
        self._rules.append(rule)

    def inspect_chunk(
        self,
        target: RuleTarget,
        chunk: str,
        current_turn: int,
    ) -> TtsrMatchResult | None:
        """Inspect token chunk against all active rules honoring repeat_gap cooldowns."""
        if not chunk or not self._rules or self._interrupt_requested:
            return None

        # Filter out rules currently undergoing quiet cooldown
        active_rules = [
            rule
            for rule in self._rules
            if current_turn - self._rule_last_triggered_turn.get(rule.rule_id, -9999) >= rule.repeat_gap
        ]
        if not active_rules:
            return None

        match = self._matcher.feed_and_match(active_rules, target, chunk, current_turn)
        if match is not None:
            self._last_match = match
            self._rule_last_triggered_turn[match.rule.rule_id] = current_turn
            if match.rule.action == "abort_and_retry":
                self._interrupt_requested = True
                logger.warning(
                    " TTSR Stream Interruption: rule=%s target=%s pattern=%s",
                    match.rule.rule_id,
                    target,
                    match.rule.pattern.pattern,
                )
            return match
        return None

    def create_interruption_message(self, match: TtsrMatchResult) -> HumanMessage:
        """Construct a system-interrupt reminder message marked with TRAP_SHIELD."""
        safe_matched = scrub_sensitive_info(match.matched_text).strip()
        matched_line = f"Offending fragment detected: {safe_matched}\n" if safe_matched else ""
        content = (
            f"<system-interrupt>\n"
            f"[Rule Intervention: {match.rule.name}]\n"
            f"{matched_line}"
            f"{match.rule.reminder}\n"
            f"</system-interrupt>"
        )
        msg = HumanMessage(content=content)
        with_message_marks(msg, WorkingMemoryMark.TRAP_SHIELD.value)
        if not hasattr(msg, "additional_kwargs") or not isinstance(msg.additional_kwargs, dict):
            msg.additional_kwargs = {}
        msg.additional_kwargs["retention"] = "persistent"
        msg.additional_kwargs["rule_id"] = match.rule.rule_id
        return msg

    def record_retry(self) -> bool:
        """Record a retry iteration this turn; returns True if within max_retries."""
        self._retries_this_turn += 1
        return self._retries_this_turn <= self._max_retries

    def reset_interruption(self) -> None:
        """Clear interruption flag and matcher buffer before starting a retry turn."""
        self._interrupt_requested = False
        self._matcher.reset()

    def reset_turn(self) -> None:
        """Reset turn-level retry counters, interruption state, and matcher buffers."""
        self._retries_this_turn = 0
        self._interrupt_requested = False
        self._last_match = None
        self._matcher.reset()
