# [INPUT]: None
# [OUTPUT]: None
# [POS]: tests/agent/context_management/test_evidence_disclosure_suite.py

"""Comprehensive unit test suite for TinySoul active and completed isomorphic evidence disclosure."""

import pytest

from myrm_agent_harness.agent.context_management.evidence_disclosure import (
    ActionDetailDescriptor,
    ActionExecutionFailure,
    ActiveEvidenceDisclosureSuite,
    EvidenceOutcome,
    EvidenceSourceState,
    QueryScopeKind,
    build_action_leaf_ref,
    build_collection_ref,
    parse_evidence_ref,
)


def test_isomorphic_parity_between_active_and_history() -> None:
    """Validate that active evidence and completed history share identical isomorphic Action schema."""
    suite = ActiveEvidenceDisclosureSuite()

    # 1. Project ongoing action in active turn
    active_desc = suite.project_active_action(
        turn_ref="session:active",
        occurrence=0,
        action_name="workspace.search",
        request={"query": "evidence", "limit": 10},
        outcome=EvidenceOutcome.SETTLED,
        result={"matched_count": 5},
        references=("file:///workspace/readme.md",),
    )

    # 2. Project completed action in history turn
    history_desc = suite.project_completed_action(
        turn_ref="session:turn/2026-10-08/1",
        occurrence=0,
        action_name="workspace.search",
        request={"query": "evidence", "limit": 10},
        outcome=EvidenceOutcome.SUCCESS,
        result={"matched_count": 5},
        references=("file:///workspace/readme.md",),
    )

    # 3. Assert isomorphic schema parity
    assert active_desc.source_state == EvidenceSourceState.ACTIVE_TURN
    assert history_desc.source_state == EvidenceSourceState.COMPLETED_HISTORY
    assert suite.verify_isomorphic_parity(active_desc, history_desc) is True

    # 4. Projections have identical structural keys
    active_proj = active_desc.to_projection()
    history_proj = history_desc.to_projection()
    assert set(active_proj.keys()) == set(history_proj.keys())
    assert active_proj["kind"] == "session_action"
    assert history_proj["kind"] == "session_action"

    # 5. Issue attestation receipts
    receipt = suite.disclose(active_desc)
    assert receipt.isomorphic_parity is True
    assert receipt.action_ref == "session:active#action/0"
    assert receipt.fingerprint == active_desc.content_hash


def test_deterministic_query_scope_isolation() -> None:
    """Ensure strict deterministic query scope boundaries without cross-scope leakage."""
    suite = ActiveEvidenceDisclosureSuite()

    active_action = suite.project_active_action(
        turn_ref="session:active",
        occurrence=0,
        action_name="bash.exec",
        request={"cmd": "ls -la"},
        outcome=EvidenceOutcome.RUNNING,
    )
    history_action = suite.project_completed_action(
        turn_ref="session:turn/2026-10-08/1",
        occurrence=0,
        action_name="bash.exec",
        request={"cmd": "git status"},
        outcome=EvidenceOutcome.SUCCESS,
    )

    # Scope 1: Active turn only - history action must not leak
    active_results = suite.locate_evidence(
        QueryScopeKind.ACTIVE_TURN,
        action_name="bash.exec",
        active_actions=(active_action,),
        history_actions=(history_action,),
    )
    assert len(active_results) == 1
    assert active_results[0].ref == "session:active#action/0"
    assert active_results[0].source_state == EvidenceSourceState.ACTIVE_TURN

    # Scope 2: Completed history only - active action must not leak
    history_results = suite.locate_evidence(
        QueryScopeKind.COMPLETED_HISTORY,
        action_name="bash.exec",
        active_actions=(active_action,),
        history_actions=(history_action,),
    )
    assert len(history_results) == 1
    assert history_results[0].ref == "session:turn/2026-10-08/1#action/0"
    assert history_results[0].source_state == EvidenceSourceState.COMPLETED_HISTORY

    # Scope 3: Unified query - retrieves both under canonical contract
    unified_results = suite.locate_evidence(
        QueryScopeKind.UNIFIED_ALL,
        action_name="bash.exec",
        active_actions=(active_action,),
        history_actions=(history_action,),
    )
    assert len(unified_results) == 2

    # Targeting specific ref
    targeted = suite.locate_evidence(
        QueryScopeKind.UNIFIED_ALL,
        target_ref="session:turn/2026-10-08/1#action/0",
        active_actions=(active_action,),
        history_actions=(history_action,),
    )
    assert len(targeted) == 1
    assert targeted[0].turn_ref == "session:turn/2026-10-08/1"


def test_bounded_real_read_pagination() -> None:
    """Verify pagination window boundaries and real-reading offset binding with sha256 checksums."""
    suite = ActiveEvidenceDisclosureSuite(default_page_size=2)

    actions = [
        suite.project_completed_action(
            turn_ref="session:turn/2026-10-08/1",
            occurrence=i,
            action_name=f"tool_step_{i}",
            request={"step": i},
            outcome=EvidenceOutcome.SUCCESS,
        )
        for i in range(5)
    ]

    # Provide real raw outputs bound to each action ref
    raw_texts = {
        action.ref: f"Real terminal output log for step {action.occurrence} with detailed stacktrace."
        for action in actions
    }

    # Page 1
    page1 = suite.paginate_and_read(
        actions,
        page_number=1,
        page_size=2,
        text_content_by_ref=raw_texts,
        max_text_window=30,
    )
    assert page1.page_number == 1
    assert page1.total_records == 5
    assert page1.total_pages == 3
    assert page1.has_next is True
    assert page1.has_previous is False
    assert len(page1.items) == 2
    assert len(page1.slices) == 2

    # Check slice binding
    slice0 = page1.slices[0]
    assert slice0.unit_id == "session:turn/2026-10-08/1#action/0"
    assert slice0.start_offset == 0
    assert slice0.end_offset == 30
    assert len(slice0.actual_text) == 30
    assert len(slice0.content_sha256) == 64

    # Page 3 (last page with 1 item)
    page3 = suite.paginate_and_read(actions, page_number=3, page_size=2)
    assert page3.page_number == 3
    assert page3.has_next is False
    assert page3.has_previous is True
    assert len(page3.items) == 1


def test_invalid_ref_and_error_handling() -> None:
    """Ensure strict validation of reference syntax, execution failure capture, and parameter guards."""
    suite = ActiveEvidenceDisclosureSuite()

    # 1. Invalid reference syntax checks
    assert suite.parse_ref("invalid_ref_without_turn") is None
    assert suite.parse_ref("session:turn/2026-10-08/1#action/-1") is None
    assert suite.parse_ref("session:turn/2026-10-08/1#unknown_fragment") is None

    # Valid refs
    assert suite.parse_ref("session:turn/2026-10-08/1#action/3") == "session:turn/2026-10-08/1#action/3"
    assert suite.parse_ref("session:turn/2026-10-08/1#actions") == "session:turn/2026-10-08/1#actions"
    assert suite.parse_ref("session:active#action/2") == "session:active#action/2"

    # Helpers
    assert build_collection_ref("session:turn/2026-10-08/2") == "session:turn/2026-10-08/2#actions"
    assert build_action_leaf_ref("session:active", 1) == "session:active#action/1"

    with pytest.raises(ValueError):
        build_action_leaf_ref("malformed_turn", 0)

    with pytest.raises(ValueError):
        build_action_leaf_ref("session:active", -1)

    # 2. Execution failure capture
    failure = ActionExecutionFailure(
        code="COMMAND_TIMEOUT",
        message="Process timed out after 30 seconds",
        details={"signal": "SIGKILL"},
    )
    failed_action = suite.project_active_action(
        turn_ref="session:active",
        occurrence=1,
        action_name="code_exec",
        request={"timeout": 30},
        outcome=EvidenceOutcome.FAILURE,
        failure=failure,
    )
    assert failed_action.outcome == EvidenceOutcome.FAILURE
    assert failed_action.failure is not None
    assert failed_action.failure.code == "COMMAND_TIMEOUT"
    proj = failed_action.to_projection()
    assert proj["failure"] == {
        "code": "COMMAND_TIMEOUT",
        "message": "Process timed out after 30 seconds",
        "details": {"signal": "SIGKILL"},
    }

    # 3. Invalid pagination parameters
    with pytest.raises(ValueError):
        suite.paginate_and_read((failed_action,), page_number=0)

    with pytest.raises(ValueError):
        suite.paginate_and_read((failed_action,), page_number=1, page_size=0)
