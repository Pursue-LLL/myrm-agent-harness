# [INPUT]: None
# [OUTPUT]: None
# [POS]: tests/agent/context_management/test_nested_approval_restore_suite.py

"""Comprehensive unit test suite for Nested Approval Restore and Compaction Rollback."""

import pytest

from myrm_agent_harness.agent.context_management.nested_approval_restore import (
    ApprovalDecisionKind,
    CompactionRollbackBudget,
    DecisionPrecedence,
    NestedApprovalRestoreSuite,
    make_approval_decision,
    make_compaction_entry,
)


def test_live_permanent_rejection_overrides_snapshot_approval() -> None:
    """Security critical: Live permanent rejection must trump stale snapshot alwaysApprove during nested resume."""
    suite = NestedApprovalRestoreSuite()

    # 1. Snapshot has stale alwaysApprove for protected tool
    snap_approval = make_approval_decision(
        grant_id="grant_db_wipe",
        tool_name="drop_database",
        agent_owner="Worker",
        decision=ApprovalDecisionKind.APPROVE,
        is_permanent=True,
        is_live=False,
        timestamp=1000.0,
    )

    # 2. Live environment has active alwaysReject (admin revoked permission)
    live_rejection = make_approval_decision(
        grant_id="grant_db_wipe",
        tool_name="drop_database",
        agent_owner="Worker",
        decision=ApprovalDecisionKind.REJECT,
        is_permanent=True,
        message="Permission permanently revoked by security admin",
        is_live=True,
        timestamp=2000.0,
    )

    # 3. Restore nested run with default LIVE_PRIORITY
    resolved, receipt = suite.restore_nested_run(
        snapshot_decisions=(snap_approval,),
        live_decisions=(live_rejection,),
        session_id="session_nested_01",
    )

    # 4. Assert live rejection takes absolute precedence
    assert len(resolved) == 1
    decision = resolved[0]
    assert decision.decision == ApprovalDecisionKind.REJECT
    assert decision.is_permanent is True
    assert decision.message == "Permission permanently revoked by security admin"
    assert decision.is_live is True

    # Audit receipt tracks the override
    assert receipt.live_overrides_applied == 1
    assert receipt.permanent_rejections_preserved == 1
    assert receipt.restored_grants_count == 1


def test_agent_owner_isolation_for_same_tool_name() -> None:
    """Validate that approval grants are strictly bound to agent_owner and cannot bleed across subagents."""
    suite = NestedApprovalRestoreSuite()

    # Outer worker has approval for shared tool 'file_write'
    outer_grant = make_approval_decision(
        grant_id="grant_outer",
        tool_name="file_write",
        agent_owner="OuterAgent",
        decision=ApprovalDecisionKind.APPROVE,
        is_permanent=True,
    )

    # Nested worker has distinct rejection for the same tool 'file_write'
    nested_grant = make_approval_decision(
        grant_id="grant_nested",
        tool_name="file_write",
        agent_owner="UntrustedSubagent",
        decision=ApprovalDecisionKind.REJECT,
        is_permanent=True,
        message="Subagent sandboxed from writes",
    )

    resolved, receipt = suite.restore_nested_run(
        snapshot_decisions=(outer_grant,),
        live_decisions=(nested_grant,),
        session_id="session_nested_02",
    )

    # Both must be preserved independently without cross-bleeding
    assert len(resolved) == 2
    by_owner = {d.agent_owner: d for d in resolved}

    assert by_owner["OuterAgent"].decision == ApprovalDecisionKind.APPROVE
    assert by_owner["UntrustedSubagent"].decision == ApprovalDecisionKind.REJECT
    assert by_owner["UntrustedSubagent"].message == "Subagent sandboxed from writes"


def test_compaction_validate_before_purge_and_rollback_budget() -> None:
    """Validate transactional compaction replacement: validate first before purge, with bounded rollback."""
    suite = NestedApprovalRestoreSuite()

    history = [
        make_compaction_entry(f"turn_{i}", f"Turn content {i}", token_count=50)
        for i in range(10)
    ]
    budget = CompactionRollbackBudget(
        max_rollback_entries=5,
        min_retained_turns=2,
        max_token_ceiling=500,
    )

    # Phase 1: Invalid summary candidate (empty content) -> MUST NOT touch history
    invalid_candidate = make_compaction_entry("cand_inv", "   ", token_count=10)
    success, current_hist, stash_id, error = suite.replace_with_compaction(
        existing_history=history,
        candidate_summary=invalid_candidate,
        budget=budget,
    )
    assert success is False
    assert stash_id is None
    assert error is not None
    assert "cannot be empty" in error
    assert len(current_hist) == 10  # Existing history intact!

    # Phase 2: Valid candidate summary -> validates and stores bounded rollback stash
    valid_candidate = make_compaction_entry(
        "cand_valid", "Summary of turns 0 to 7", token_count=120
    )
    success, compacted_hist, stash_id, error = suite.replace_with_compaction(
        existing_history=history,
        candidate_summary=valid_candidate,
        budget=budget,
    )
    assert success is True
    assert stash_id is not None
    assert error is None
    # compacted history = 1 summary + 2 retained recent turns = 3
    assert len(compacted_hist) == 3
    assert compacted_hist[0].entry_id == "cand_valid"
    assert compacted_hist[1].entry_id == "turn_8"
    assert compacted_hist[2].entry_id == "turn_9"

    # Phase 3: Rollback on runtime anomaly -> seamlessly restore stashed entries
    restored_hist = suite.rollback_compaction(stash_id, compacted_hist)
    # Stash held bounded 5 entries (turns 3..7) + 2 tail turns = 7
    assert len(restored_hist) == 7
    assert restored_hist[-1].entry_id == "turn_9"

    # Phase 4: Discard stash
    assert suite.discard_compaction_stash(stash_id) is True
    with pytest.raises(KeyError):
        suite.rollback_compaction(stash_id, compacted_hist)


def test_boundary_empty_and_precedence_strategies() -> None:
    """Validate empty decision edge cases and SNAPSHOT_ONLY / MERGE_SAVED strategies."""
    suite = NestedApprovalRestoreSuite()

    # 1. Empty sets
    resolved, receipt = suite.restore_nested_run(
        snapshot_decisions=(),
        live_decisions=(),
        session_id="session_empty",
    )
    assert len(resolved) == 0
    assert receipt.restored_grants_count == 0

    # 2. SNAPSHOT_ONLY strategy
    snap_grant = make_approval_decision(
        "g1", "bash", "Worker", ApprovalDecisionKind.APPROVE, timestamp=10.0
    )
    live_grant = make_approval_decision(
        "g1", "bash", "Worker", ApprovalDecisionKind.REJECT, timestamp=20.0
    )

    snap_only_resolved, _ = suite.restore_nested_run(
        snapshot_decisions=(snap_grant,),
        live_decisions=(live_grant,),
        session_id="session_snap_only",
        precedence=DecisionPrecedence.SNAPSHOT_ONLY,
    )
    assert len(snap_only_resolved) == 1
    assert snap_only_resolved[0].decision == ApprovalDecisionKind.APPROVE

    # 3. MERGE_SAVED strategy: permanent rejection trumps more recent approval
    perm_reject = make_approval_decision(
        "g2", "delete_file", "Worker", ApprovalDecisionKind.REJECT, is_permanent=True, timestamp=5.0
    )
    recent_approve = make_approval_decision(
        "g2", "delete_file", "Worker", ApprovalDecisionKind.APPROVE, is_permanent=False, timestamp=50.0
    )
    merge_resolved, _ = suite.restore_nested_run(
        snapshot_decisions=(perm_reject,),
        live_decisions=(recent_approve,),
        session_id="session_merge",
        precedence=DecisionPrecedence.MERGE_SAVED,
    )
    assert len(merge_resolved) == 1
    assert merge_resolved[0].decision == ApprovalDecisionKind.REJECT
