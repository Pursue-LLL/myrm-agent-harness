"""Context Threshold Model Downshift Governor.

[INPUT]
- .schemas::DownshiftConfig, DownshiftState, HandoffMemo, ModelTier, DownshiftTriggerMode
- ..strategies.session_notes.schemas::SessionNotes

[OUTPUT]
- DownshiftGovernor: Stateful manager for evaluating and driving model downshifts per session.

[POS]
Pure domain governor handling deterministic threshold gating, handover memo composition from
session notes, and fallback-up resilience.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from myrm_agent_harness.agent.context_management.downshift.schemas import (
    DownshiftConfig,
    DownshiftState,
    DownshiftTriggerMode,
    HandoffMemo,
    ModelTier,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.agent.context_management.strategies.session_notes.schemas import (
        SessionNotes,
    )

logger = get_agent_logger(__name__)


class DownshiftGovernor:
    """Evaluates context consumption against budget thresholds and governs tier downshifts."""

    def __init__(self, config: DownshiftConfig | None = None) -> None:
        self.config = config or DownshiftConfig()
        self._states: dict[str, DownshiftState] = {}

    def get_or_create_state(self, session_id: str) -> DownshiftState:
        if session_id not in self._states:
            self._states[session_id] = DownshiftState(session_id=session_id)
        return self._states[session_id]

    def revoke_downshift(self, session_id: str) -> bool:
        """Manually revoke downshift and restore Premium tier."""
        state = self.get_or_create_state(session_id)
        state.is_downshifted = False
        state.current_tier = ModelTier.PREMIUM
        state.manually_revoked = True
        state.consecutive_economy_failures = 0
        logger.info(f"Session {session_id}: Downshift manually revoked -> restored to PREMIUM")
        return True

    def check_and_apply_downshift(
        self,
        session_id: str,
        current_tokens: int,
        max_context_tokens: int,
        current_wu: float = 0.0,
        turn_index: int = 0,
        current_model_name: str = "unknown",
        session_notes: SessionNotes | None = None,
    ) -> tuple[bool, DownshiftState]:
        """Check if downshift condition is met and apply transition if valid."""
        state = self.get_or_create_state(session_id)

        if not self.config.enabled:
            return False, state

        if state.manually_revoked or state.is_downshifted:
            return False, state

        usage_ratio = current_tokens / max(max_context_tokens, 1)
        token_exceeded = usage_ratio >= self.config.context_usage_pct_threshold
        wu_exceeded = current_wu >= self.config.wu_threshold

        triggered = False
        reason = ""

        if self.config.trigger_mode == DownshiftTriggerMode.TOKEN_PERCENT and token_exceeded:
            triggered = True
            reason = f"Context usage ratio {usage_ratio:.2%} >= threshold {self.config.context_usage_pct_threshold:.2%}"
        elif self.config.trigger_mode == DownshiftTriggerMode.WORK_UNITS and wu_exceeded:
            triggered = True
            reason = f"Work units {current_wu:.2f} >= threshold {self.config.wu_threshold:.2f}"
        elif self.config.trigger_mode == DownshiftTriggerMode.BOTH and (token_exceeded or wu_exceeded):
            triggered = True
            reason = (
                f"Dual trigger: token_ratio={usage_ratio:.2%} (exceeded={token_exceeded}), "
                f"wu={current_wu:.2f} (exceeded={wu_exceeded})"
            )

        if triggered:
            memo = self.build_handoff_memo(
                session_id=session_id,
                turn_index=turn_index,
                source_model=current_model_name,
                target_tier=ModelTier.ECONOMY,
                session_notes=session_notes,
            )
            state.is_downshifted = True
            state.current_tier = ModelTier.ECONOMY
            state.downshifted_turn = turn_index
            state.downshift_reason = reason
            state.handoff_memo = memo
            state.consecutive_economy_failures = 0
            logger.info(f"Session {session_id}: Downshifted to ECONOMY. Reason: {reason}")
            return True, state

        return False, state

    def record_economy_outcome(
        self,
        session_id: str,
        success: bool,
    ) -> tuple[bool, DownshiftState]:
        """Record outcome of economy model turn and check for fallback-up threshold."""
        state = self.get_or_create_state(session_id)
        if not state.is_downshifted or state.current_tier != ModelTier.ECONOMY:
            return False, state

        if success:
            state.consecutive_economy_failures = 0
            return False, state

        state.consecutive_economy_failures += 1
        logger.warning(
            f"Session {session_id}: Economy model failure recorded. "
            f"Consecutive failures: {state.consecutive_economy_failures}/{self.config.max_consecutive_economy_failures}"
        )

        if (
            self.config.auto_fallback_up
            and state.consecutive_economy_failures >= self.config.max_consecutive_economy_failures
        ):
            state.current_tier = ModelTier.PREMIUM
            state.fallback_up_count += 1
            state.consecutive_economy_failures = 0
            logger.warning(
                f"Session {session_id}: Fallback-Up triggered! Restored to PREMIUM tier "
                f"(fallback count: {state.fallback_up_count})"
            )
            return True, state

        return False, state

    @staticmethod
    def build_handoff_memo(
        session_id: str,
        turn_index: int,
        source_model: str,
        target_tier: ModelTier,
        session_notes: SessionNotes | None = None,
    ) -> HandoffMemo:
        """Extract structured data from SessionNotes into a clean HandoffMemo."""
        memo = HandoffMemo(
            session_id=session_id,
            turn_index=turn_index,
            source_model=source_model,
            target_tier=target_tier,
        )
        if not session_notes:
            return memo

        for section in session_notes.sections:
            k = section.key.lower()
            if k == "task_spec":
                memo.task_spec = section.content
            elif k == "current_state":
                memo.current_state = section.content
            elif k == "files_and_functions":
                memo.files_and_functions = section.content
            elif k == "errors_and_corrections":
                memo.errors_and_corrections = section.content
            elif k in ("remaining_steps", "next_steps", "workflow"):
                if not memo.remaining_steps:
                    memo.remaining_steps = section.content
                else:
                    memo.remaining_steps += f"\n{section.content}"

        return memo
