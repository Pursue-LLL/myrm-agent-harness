"""Comprehensive unit tests for AccountWideIdleChatAutoArchivePolicySuite.

[INPUT]
- auto_archive domain models, evaluator, coordinator, and facade suite.

[OUTPUT]
- Deterministic verification of exemption precedence, threshold clamping,
  batch sweep auditing, callback execution, and facade lazy exports.

[POS]
- Sub-package: tests.agent.context_management
- Module: test_account_wide_idle_chat_auto_archive_policy_suite.py
"""

from typing import List

import pytest

from myrm_agent_harness.agent import (
    AccountWideIdleChatAutoArchivePolicySuite as RootExportedSuite,
)
from myrm_agent_harness.agent.context_management import (
    AccountWideIdleChatAutoArchivePolicySuite,
    ArchiveEligibilityVerdict,
    ArchiveEvaluationResult,
    ArchiveExemptionReason,
    ArchivePolicyEvaluator,
    ArchiveSweepCoordinator,
    ArchiveSweepSummary,
    AutoArchivePolicyConfig,
    ChatSessionMetadata,
)


def test_policy_config_clamping_and_disabled() -> None:
    """Verifies that idle thresholds are clamped to safety bounds and master toggle disables sweep."""
    # Under min bound (e.g. 10s < 3600s) -> clamped to 3600
    cfg_low = AutoArchivePolicyConfig(enabled=True, idle_threshold_seconds=10)
    assert cfg_low.get_clamped_threshold() == 3600

    # Over max bound -> clamped to 1 year
    cfg_high = AutoArchivePolicyConfig(enabled=True, idle_threshold_seconds=100_000_000)
    assert cfg_high.get_clamped_threshold() == 86400 * 365

    # Master disabled
    cfg_disabled = AutoArchivePolicyConfig(enabled=False, idle_threshold_seconds=7200)
    evaluator = ArchivePolicyEvaluator(cfg_disabled)
    session = ChatSessionMetadata(chat_id="chat-1", last_active_timestamp=1000.0)

    res = evaluator.evaluate_session(session, now_timestamp=50000.0)
    assert res.verdict == ArchiveEligibilityVerdict.EXEMPT
    assert res.reason == ArchiveExemptionReason.DISABLED


def test_policy_evaluator_exemption_precedence() -> None:
    """Verifies that pinned, running task, and already archived sessions are strictly exempted."""
    cfg = AutoArchivePolicyConfig(
        enabled=True,
        idle_threshold_seconds=3600,
        include_user_created=False,
    )
    evaluator = ArchivePolicyEvaluator(cfg)
    now = 100_000.0
    stale_time = now - 10_000.0  # 10,000s idle > 3600s threshold

    # 1. Pinned
    s_pinned = ChatSessionMetadata(
        chat_id="pinned-1",
        last_active_timestamp=stale_time,
        is_pinned=True,
    )
    res_pinned = evaluator.evaluate_session(s_pinned, now)
    assert res_pinned.verdict == ArchiveEligibilityVerdict.EXEMPT
    assert res_pinned.reason == ArchiveExemptionReason.PINNED

    # 2. Running task
    s_running = ChatSessionMetadata(
        chat_id="running-1",
        last_active_timestamp=stale_time,
        has_running_task=True,
    )
    res_running = evaluator.evaluate_session(s_running, now)
    assert res_running.verdict == ArchiveEligibilityVerdict.EXEMPT
    assert res_running.reason == ArchiveExemptionReason.ACTIVE_TURN_RUNNING

    # 3. Already archived
    s_archived = ChatSessionMetadata(
        chat_id="archived-1",
        last_active_timestamp=stale_time,
        is_archived=True,
    )
    res_archived = evaluator.evaluate_session(s_archived, now)
    assert res_archived.verdict == ArchiveEligibilityVerdict.EXEMPT
    assert res_archived.reason == ArchiveExemptionReason.ALREADY_ARCHIVED

    # 4. User-created exempted by toggle
    s_user = ChatSessionMetadata(
        chat_id="user-1",
        last_active_timestamp=stale_time,
        is_user_created=True,
    )
    res_user = evaluator.evaluate_session(s_user, now)
    assert res_user.verdict == ArchiveEligibilityVerdict.EXEMPT
    assert res_user.reason == ArchiveExemptionReason.USER_CREATED_EXEMPTED


def test_policy_evaluator_idle_duration_eligibility() -> None:
    """Verifies that only sessions exceeding the threshold without exemptions are eligible."""
    cfg = AutoArchivePolicyConfig(
        enabled=True,
        idle_threshold_seconds=7200,
        include_user_created=True,
    )
    evaluator = ArchivePolicyEvaluator(cfg)
    now = 50_000.0

    # Recent session (1000s idle < 7200s) -> Not idle
    s_recent = ChatSessionMetadata(chat_id="recent-1", last_active_timestamp=now - 1000.0)
    res_recent = evaluator.evaluate_session(s_recent, now)
    assert res_recent.verdict == ArchiveEligibilityVerdict.EXEMPT
    assert res_recent.reason == ArchiveExemptionReason.NOT_IDLE
    assert res_recent.idle_duration_seconds == 1000.0

    # Old session (10000s idle > 7200s) -> Eligible!
    s_old = ChatSessionMetadata(chat_id="old-1", last_active_timestamp=now - 10_000.0)
    res_old = evaluator.evaluate_session(s_old, now)
    assert res_old.verdict == ArchiveEligibilityVerdict.ELIGIBLE
    assert res_old.reason == ArchiveExemptionReason.NONE
    assert res_old.idle_duration_seconds == 10_000.0


def test_sweep_coordinator_batch_filtering_and_breakdown() -> None:
    """Verifies that sweep coordinator aggregates candidate breakdowns and handles simulated archiving."""
    cfg = AutoArchivePolicyConfig(enabled=True, idle_threshold_seconds=3600)
    evaluator = ArchivePolicyEvaluator(cfg)
    coordinator = ArchiveSweepCoordinator(evaluator)
    now = 100_000.0

    sessions = [
        ChatSessionMetadata(chat_id="c1", last_active_timestamp=now - 10_000.0),  # eligible
        ChatSessionMetadata(chat_id="c2", last_active_timestamp=now - 10_000.0, is_pinned=True),  # pinned
        ChatSessionMetadata(chat_id="c3", last_active_timestamp=now - 500.0),  # not_idle
        ChatSessionMetadata(chat_id="c4", last_active_timestamp=now - 20_000.0),  # eligible
    ]

    summary, results = coordinator.run_sweep(sessions, now_timestamp=now)

    assert summary.total_scanned == 4
    assert summary.eligible_count == 2
    assert summary.archived_count == 2  # Without callback, simulated equals eligible
    assert len(results) == 4

    breakdown_dict = dict(summary.exempt_breakdown)
    assert breakdown_dict.get(ArchiveExemptionReason.PINNED.value) == 1
    assert breakdown_dict.get(ArchiveExemptionReason.NOT_IDLE.value) == 1


def test_sweep_coordinator_with_execution_callback() -> None:
    """Verifies that external archive callback receives eligible chat IDs and records actual counts."""
    cfg = AutoArchivePolicyConfig(enabled=True, idle_threshold_seconds=3600)
    evaluator = ArchivePolicyEvaluator(cfg)
    coordinator = ArchiveSweepCoordinator(evaluator)
    now = 50_000.0

    archived_ids: List[str] = []

    def mock_archive(cid: str) -> bool:
        if cid == "fail-me":
            return False
        if cid == "crash-me":
            raise RuntimeError("Database error")
        archived_ids.append(cid)
        return True

    sessions = [
        ChatSessionMetadata(chat_id="ok-1", last_active_timestamp=now - 5000.0),
        ChatSessionMetadata(chat_id="ok-2", last_active_timestamp=now - 6000.0),
        ChatSessionMetadata(chat_id="fail-me", last_active_timestamp=now - 7000.0),
        ChatSessionMetadata(chat_id="crash-me", last_active_timestamp=now - 8000.0),
    ]

    summary, _ = coordinator.run_sweep(sessions, now_timestamp=now, archive_action=mock_archive)

    assert summary.total_scanned == 4
    assert summary.eligible_count == 4
    assert summary.archived_count == 2  # Only ok-1 and ok-2 returned True
    assert archived_ids == ["ok-1", "ok-2"]


def test_suite_facade_and_root_exports() -> None:
    """Verifies facade operations, policy clamping, and root-level lazy exports."""
    suite = AccountWideIdleChatAutoArchivePolicySuite(
        AutoArchivePolicyConfig(enabled=True, idle_threshold_seconds=3600)
    )

    clamped = suite.clamp_policy(AutoArchivePolicyConfig(idle_threshold_seconds=50))
    assert clamped.idle_threshold_seconds == 3600

    now = 20_000.0
    res = suite.evaluate_session(
        ChatSessionMetadata(chat_id="f1", last_active_timestamp=now - 5000.0),
        now_timestamp=now,
    )
    assert res.verdict == ArchiveEligibilityVerdict.ELIGIBLE

    # Verify root lazy exports
    assert RootExportedSuite is AccountWideIdleChatAutoArchivePolicySuite
    inst = RootExportedSuite()
    assert isinstance(inst, AccountWideIdleChatAutoArchivePolicySuite)
    assert inst.evaluator is not None
    assert inst.coordinator is not None
