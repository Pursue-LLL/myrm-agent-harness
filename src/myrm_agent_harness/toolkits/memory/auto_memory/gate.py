# [POS]: src/myrm_agent_harness/toolkits/memory/auto_memory/gate.py
# [INPUT]: SessionActivitySnapshot, AutoMemoryBudgetPolicy, now_timestamp
# [OUTPUT]: AutoMemoryGate, evaluate gating decisions

"""Dual-gate evaluation engine enforcing turn count and token budget thresholds.

Prevents trivial conversation debris from polluting the memory store and protects
user token budgets from autonomous background consumption.
"""

from __future__ import annotations

import time

from myrm_agent_harness.toolkits.memory.auto_memory.models import (
    AutoMemoryBudgetPolicy,
    AutoMemoryGatingDecision,
    SessionActivitySnapshot,
)


class AutoMemoryGate:
    """Stateless evaluator enforcing idle timeouts and dual-gate criteria."""

    @staticmethod
    def is_session_idle(
        snapshot: SessionActivitySnapshot,
        policy: AutoMemoryBudgetPolicy,
        now_ts: float | None = None,
    ) -> bool:
        """Check whether the session has been inactive past the configured timeout window."""
        current_time = now_ts if now_ts is not None else time.time()
        elapsed_inactive_seconds = current_time - snapshot.last_active_at_timestamp
        return elapsed_inactive_seconds >= policy.idle_timeout_seconds

    @staticmethod
    def is_turn_count_sufficient(
        snapshot: SessionActivitySnapshot,
        policy: AutoMemoryBudgetPolicy,
    ) -> bool:
        """Gate 1: Check whether session has enough completed turns to warrant consolidation."""
        return snapshot.turn_count >= policy.min_turns_threshold

    @staticmethod
    def is_budget_healthy(
        snapshot: SessionActivitySnapshot,
        policy: AutoMemoryBudgetPolicy,
    ) -> bool:
        """Gate 2: Check whether cumulative tokens are within safe operating limits."""
        # Check both session-specific and global/account consumed levels
        if snapshot.total_tokens_consumed >= policy.max_token_budget_ceiling:
            return False
        return policy.current_consumed_tokens < policy.max_token_budget_ceiling

    def evaluate(
        self,
        snapshot: SessionActivitySnapshot,
        policy: AutoMemoryBudgetPolicy,
        total_message_chars: int = 0,
        now_ts: float | None = None,
        force_ignore_idle: bool = False,
    ) -> tuple[bool, AutoMemoryGatingDecision, str]:
        """Perform comprehensive gating evaluation across all criteria.

        Returns:
            (is_eligible, decision_code, explanatory_reason)
        """
        # Criterion 0: Check if there are any unconsolidated turns
        if not snapshot.has_unconsolidated_turns:
            return (
                False,
                AutoMemoryGatingDecision.ALREADY_CONSOLIDATED,
                f"Session '{snapshot.session_id}' has already been consolidated; no new turns.",
            )

        # Criterion 1: Idle-timeout check (unless caller forces trigger e.g. manual flush or session end)
        if not force_ignore_idle and not self.is_session_idle(snapshot, policy, now_ts):
            current_time = now_ts if now_ts is not None else time.time()
            elapsed = max(0.0, current_time - snapshot.last_active_at_timestamp)
            return (
                False,
                AutoMemoryGatingDecision.SKIPPED_NOT_IDLE,
                f"Session '{snapshot.session_id}' is active (idle for {elapsed:.1f}s, threshold {policy.idle_timeout_seconds:.1f}s).",
            )

        # Criterion 2: Turn count threshold ("dialogue too short, do not record")
        if not self.is_turn_count_sufficient(snapshot, policy):
            return (
                False,
                AutoMemoryGatingDecision.SKIPPED_SHORT_CONVERSATION,
                f"Session has only {snapshot.turn_count} turns (min threshold {policy.min_turns_threshold}).",
            )

        # Criterion 3: Information density check (total content characters)
        if total_message_chars > 0 and total_message_chars < policy.min_unconsolidated_char_count:
            return (
                False,
                AutoMemoryGatingDecision.SKIPPED_LOW_INFORMATION,
                f"Content volume too short ({total_message_chars} chars, min {policy.min_unconsolidated_char_count} chars).",
            )

        # Criterion 4: Token budget ceiling check ("quota depleted, do not record")
        if not self.is_budget_healthy(snapshot, policy):
            return (
                False,
                AutoMemoryGatingDecision.SKIPPED_BUDGET_EXHAUSTED,
                f"Token budget ceiling reached ({snapshot.total_tokens_consumed} >= {policy.max_token_budget_ceiling}).",
            )

        return (
            True,
            AutoMemoryGatingDecision.ACCEPTED,
            f"Session '{snapshot.session_id}' meets all idle and dual-gate criteria.",
        )
