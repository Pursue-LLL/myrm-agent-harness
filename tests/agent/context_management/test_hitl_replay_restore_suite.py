"""Unit tests for CopilotKit reconnect passive replay and selective HITL restoration suite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.hitl_replay_restore import (
    CopilotKitHITLReplayRestoreSuite,
    HITLApprovalState,
    PendingHITLDescriptor,
    ReplayRestorationSummary,
    ToolCallReplayItem,
    ToolExecutionType,
    ToolResultReplayItem,
)


def test_ordinary_tools_remain_passive_during_reconnect_replay() -> None:
    """Test ordinary side-effect tools remain strictly passive and unexecuted during reconnect replay."""
    suite = CopilotKitHITLReplayRestoreSuite()
    session_id = "sess_passive_001"

    calls = [
        ToolCallReplayItem(
            tool_call_id="call_ord_1",
            tool_name="write_file",
            tool_type=ToolExecutionType.ORDINARY,
            arguments={"path": "/app/config.json", "content": "{}"},
        ),
        ToolCallReplayItem(
            tool_call_id="call_ord_2",
            tool_name="execute_shell",
            tool_type=ToolExecutionType.ORDINARY,
            arguments={"command": "npm install"},
        ),
    ]
    results = [
        ToolResultReplayItem(
            tool_call_id="call_ord_1",
            content="File written successfully",
        )
    ]

    summary: ReplayRestorationSummary = suite.handle_reconnect_replay(
        session_id=session_id,
        tool_calls=calls,
        tool_results=results,
    )

    assert summary.session_id == session_id
    assert summary.passive_tools_skipped == 2
    assert summary.completed_hitl_skipped == 0
    assert len(summary.restored_pending_hitl) == 0
    assert summary.is_awaiting_user_approval is False
    assert len(suite.list_pending_approvals(session_id)) == 0


def test_pending_hitl_selectively_restored_and_answered_continues() -> None:
    """Test un-answered HITL requests are restored to pending queue and continue upon user approval."""
    suite = CopilotKitHITLReplayRestoreSuite()
    session_id = "sess_hitl_002"

    hitl_call = ToolCallReplayItem(
        tool_call_id="call_hitl_pending_1",
        tool_name="approve_production_deployment",
        tool_type=ToolExecutionType.HUMAN_IN_THE_LOOP,
        arguments={"cluster": "us-east-prod", "version": "v2.4.0"},
        prompt_description="Deploy version v2.4.0 to production cluster?",
    )

    # Replay stream with pending HITL (no result item)
    summary: ReplayRestorationSummary = suite.handle_reconnect_replay(
        session_id=session_id,
        tool_calls=[hitl_call],
        tool_results=[],
    )

    assert summary.is_awaiting_user_approval is True
    assert len(summary.restored_pending_hitl) == 1
    restored: PendingHITLDescriptor = summary.restored_pending_hitl[0]
    assert restored.tool_call_id == "call_hitl_pending_1"
    assert restored.state == HITLApprovalState.PENDING
    assert restored.prompt_description == "Deploy version v2.4.0 to production cluster?"

    # Check active pending queue
    pending_list = suite.list_pending_approvals(session_id)
    assert len(pending_list) == 1
    assert pending_list[0].tool_call_id == "call_hitl_pending_1"

    # User answers and approves the pending HITL
    decision_receipt: ToolResultReplayItem = suite.resolve_hitl_approval(
        session_id=session_id,
        tool_call_id="call_hitl_pending_1",
        approved=True,
        response_content="Approved by SRE lead: deployment authorized.",
    )

    assert decision_receipt.tool_call_id == "call_hitl_pending_1"
    assert decision_receipt.is_error is False
    assert "deployment authorized" in decision_receipt.content

    # Active pending queue is now empty
    assert len(suite.list_pending_approvals(session_id)) == 0


def test_completed_hitl_not_reopened_nor_reexecuted() -> None:
    """Test already-answered HITL interactions are skipped and never reopened as pending."""
    suite = CopilotKitHITLReplayRestoreSuite()
    session_id = "sess_hitl_003"

    answered_call = ToolCallReplayItem(
        tool_call_id="call_hitl_done_1",
        tool_name="approve_refund",
        tool_type=ToolExecutionType.HUMAN_IN_THE_LOOP,
        arguments={"amount": "150.00"},
        prompt_description="Authorize refund of $150.00?",
    )
    answered_result = ToolResultReplayItem(
        tool_call_id="call_hitl_done_1",
        content="Refund approved earlier by operator",
        is_error=False,
    )

    summary: ReplayRestorationSummary = suite.handle_reconnect_replay(
        session_id=session_id,
        tool_calls=[answered_call],
        tool_results=[answered_result],
    )

    assert summary.completed_hitl_skipped == 1
    assert len(summary.restored_pending_hitl) == 0
    assert summary.is_awaiting_user_approval is False
    assert len(suite.list_pending_approvals(session_id)) == 0


def test_mixed_replay_stream_isolation_and_unregistered_rejection() -> None:
    """Test comprehensive mixed replay isolation and guard against resolving invalid tool IDs."""
    suite = CopilotKitHITLReplayRestoreSuite()
    session_id = "sess_hitl_004"

    calls = [
        ToolCallReplayItem(
            tool_call_id="c1_ord",
            tool_name="query_database",
            tool_type=ToolExecutionType.ORDINARY,
        ),
        ToolCallReplayItem(
            tool_call_id="c2_hitl_done",
            tool_name="grant_admin_access",
            tool_type=ToolExecutionType.HUMAN_IN_THE_LOOP,
        ),
        ToolCallReplayItem(
            tool_call_id="c3_hitl_pending",
            tool_name="execute_destructive_migration",
            tool_type=ToolExecutionType.HUMAN_IN_THE_LOOP,
            arguments={"tables": "users,orders"},
        ),
    ]
    results = [
        ToolResultReplayItem(tool_call_id="c1_ord", content="Rows returned: 42"),
        ToolResultReplayItem(tool_call_id="c2_hitl_done", content="Access granted"),
    ]

    summary = suite.handle_reconnect_replay(
        session_id=session_id,
        tool_calls=calls,
        tool_results=results,
    )

    assert summary.passive_tools_skipped == 1
    assert summary.completed_hitl_skipped == 1
    assert len(summary.restored_pending_hitl) == 1
    assert summary.restored_pending_hitl[0].tool_call_id == "c3_hitl_pending"

    # Rejecting resolution of non-pending or completed tool call raises KeyError
    with pytest.raises(KeyError, match="Cannot submit decision"):
        suite.resolve_hitl_approval(
            session_id=session_id,
            tool_call_id="c2_hitl_done",
            approved=True,
            response_content="Should fail",
        )

    with pytest.raises(KeyError, match="Cannot submit decision"):
        suite.resolve_hitl_approval(
            session_id=session_id,
            tool_call_id="non_existent_call_id",
            approved=False,
            response_content="Should fail",
        )
