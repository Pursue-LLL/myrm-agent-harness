"""Unified facade suite for account-wide idle chat auto-archive policy.

[INPUT]
- auto_archive_types: AutoArchivePolicyConfig, ChatSessionMetadata,
  ArchiveEvaluationResult, ArchiveSweepSummary.
- archive_policy_evaluator: ArchivePolicyEvaluator.
- archive_sweep_coordinator: ArchiveSweepCoordinator.

[OUTPUT]
- AccountWideIdleChatAutoArchivePolicySuite: Facade entrypoint for auto-archive orchestration.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.auto_archive
- Module: auto_archive_suite.py
"""

import time
from typing import Callable, Optional, Sequence, Tuple

from myrm_agent_harness.agent.context_management.auto_archive.archive_policy_evaluator import (
    ArchivePolicyEvaluator,
)
from myrm_agent_harness.agent.context_management.auto_archive.archive_sweep_coordinator import (
    ArchiveSweepCoordinator,
)
from myrm_agent_harness.agent.context_management.auto_archive.auto_archive_types import (
    ArchiveEvaluationResult,
    ArchiveSweepSummary,
    AutoArchivePolicyConfig,
    ChatSessionMetadata,
)


class AccountWideIdleChatAutoArchivePolicySuite:
    """Unified entrypoint for policy evaluation, clamping, and sweep orchestration."""

    def __init__(self, config: Optional[AutoArchivePolicyConfig] = None) -> None:
        self._config = config if config is not None else AutoArchivePolicyConfig()
        self._evaluator = ArchivePolicyEvaluator(self._config)
        self._coordinator = ArchiveSweepCoordinator(self._evaluator)

    @property
    def config(self) -> AutoArchivePolicyConfig:
        """Returns the current policy configuration."""
        return self._config

    @property
    def evaluator(self) -> ArchivePolicyEvaluator:
        """Returns the policy evaluator."""
        return self._evaluator

    @property
    def coordinator(self) -> ArchiveSweepCoordinator:
        """Returns the sweep coordinator."""
        return self._coordinator

    def evaluate_session(
        self, session: ChatSessionMetadata, now_timestamp: Optional[float] = None
    ) -> ArchiveEvaluationResult:
        """Evaluates a single session against the active auto-archive policy."""
        ref_time = now_timestamp if now_timestamp is not None else time.time()
        return self._evaluator.evaluate_session(session, ref_time)

    def run_sweep(
        self,
        sessions: Sequence[ChatSessionMetadata],
        now_timestamp: Optional[float] = None,
        archive_action: Optional[Callable[[str], bool]] = None,
    ) -> Tuple[ArchiveSweepSummary, Tuple[ArchiveEvaluationResult, ...]]:
        """Runs an automated sweep across multiple candidate sessions."""
        return self._coordinator.run_sweep(
            sessions=sessions,
            now_timestamp=now_timestamp,
            archive_action=archive_action,
        )

    @staticmethod
    def clamp_policy(config: AutoArchivePolicyConfig) -> AutoArchivePolicyConfig:
        """Returns a sanitized policy with idle threshold bounded safely."""
        clamped_threshold = config.get_clamped_threshold()
        return AutoArchivePolicyConfig(
            enabled=config.enabled,
            idle_threshold_seconds=clamped_threshold,
            include_user_created=config.include_user_created,
            min_idle_threshold_seconds=config.min_idle_threshold_seconds,
            max_idle_threshold_seconds=config.max_idle_threshold_seconds,
        )
