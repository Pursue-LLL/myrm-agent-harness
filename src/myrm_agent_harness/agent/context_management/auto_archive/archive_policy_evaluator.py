"""Deterministic policy evaluator for idle chat session archiving.

[INPUT]
- auto_archive_types: AutoArchivePolicyConfig, ChatSessionMetadata,
  ArchiveEvaluationResult, ArchiveEligibilityVerdict, ArchiveExemptionReason.

[OUTPUT]
- ArchivePolicyEvaluator: Pure domain evaluator classifying session eligibility.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.auto_archive
- Module: archive_policy_evaluator.py
"""

from myrm_agent_harness.agent.context_management.auto_archive.auto_archive_types import (
    ArchiveEligibilityVerdict,
    ArchiveEvaluationResult,
    ArchiveExemptionReason,
    AutoArchivePolicyConfig,
    ChatSessionMetadata,
)


class ArchivePolicyEvaluator:
    """Evaluates individual session metadata against account-wide auto-archive rules."""

    def __init__(self, config: AutoArchivePolicyConfig) -> None:
        self._config = config

    @property
    def config(self) -> AutoArchivePolicyConfig:
        """Returns the active policy configuration."""
        return self._config

    def evaluate_session(
        self, session: ChatSessionMetadata, now_timestamp: float
    ) -> ArchiveEvaluationResult:
        """Evaluates whether a candidate chat session should be archived.

        Args:
            session: Snapshot metadata of the candidate chat session.
            now_timestamp: Current unix epoch time in seconds.

        Returns:
            ArchiveEvaluationResult detailing the verdict and diagnostic reason.
        """
        idle_duration = max(0.0, now_timestamp - session.last_active_timestamp)

        # 1. Master toggle check
        if not self._config.enabled:
            return ArchiveEvaluationResult(
                chat_id=session.chat_id,
                verdict=ArchiveEligibilityVerdict.EXEMPT,
                reason=ArchiveExemptionReason.DISABLED,
                idle_duration_seconds=idle_duration,
                diagnostic_message="Auto-archive policy is disabled for this account",
            )

        # 2. Already archived sessions are skipped
        if session.is_archived:
            return ArchiveEvaluationResult(
                chat_id=session.chat_id,
                verdict=ArchiveEligibilityVerdict.EXEMPT,
                reason=ArchiveExemptionReason.ALREADY_ARCHIVED,
                idle_duration_seconds=idle_duration,
                diagnostic_message="Session is already marked as archived",
            )

        # 3. Pinned sessions are permanently exempt
        if session.is_pinned:
            return ArchiveEvaluationResult(
                chat_id=session.chat_id,
                verdict=ArchiveEligibilityVerdict.EXEMPT,
                reason=ArchiveExemptionReason.PINNED,
                idle_duration_seconds=idle_duration,
                diagnostic_message="Session is explicitly pinned by the user",
            )

        # 4. In-flight agent turns / background tasks prevent archiving
        if session.has_running_task:
            return ArchiveEvaluationResult(
                chat_id=session.chat_id,
                verdict=ArchiveEligibilityVerdict.EXEMPT,
                reason=ArchiveExemptionReason.ACTIVE_TURN_RUNNING,
                idle_duration_seconds=idle_duration,
                diagnostic_message="Session currently possesses active in-flight turns",
            )

        # 5. User-created sessions exemption filter
        if session.is_user_created and not self._config.include_user_created:
            return ArchiveEvaluationResult(
                chat_id=session.chat_id,
                verdict=ArchiveEligibilityVerdict.EXEMPT,
                reason=ArchiveExemptionReason.USER_CREATED_EXEMPTED,
                idle_duration_seconds=idle_duration,
                diagnostic_message="User-created sessions are exempted by policy toggle",
            )

        # 6. Idle threshold boundary comparison
        threshold = self._config.get_clamped_threshold()
        if idle_duration < threshold:
            return ArchiveEvaluationResult(
                chat_id=session.chat_id,
                verdict=ArchiveEligibilityVerdict.EXEMPT,
                reason=ArchiveExemptionReason.NOT_IDLE,
                idle_duration_seconds=idle_duration,
                diagnostic_message=(
                    f"Idle duration ({idle_duration:.1f}s) has not reached threshold ({threshold}s)"
                ),
            )

        # 7. Qualified for archiving
        return ArchiveEvaluationResult(
            chat_id=session.chat_id,
            verdict=ArchiveEligibilityVerdict.ELIGIBLE,
            reason=ArchiveExemptionReason.NONE,
            idle_duration_seconds=idle_duration,
            diagnostic_message=(
                f"Session is idle for {idle_duration:.1f}s, exceeding threshold ({threshold}s)"
            ),
        )
