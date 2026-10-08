"""Unit test suite for Externally Visible Irreversible Action Static Classification Gate."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.externally_visible_action import (
    ActionVisibilityScope,
    ExternallyVisibleActionGate,
)
from myrm_agent_harness.core.security.tool_registry.registry import SafetyMetadata


@pytest.fixture
def gate() -> ExternallyVisibleActionGate:
    return ExternallyVisibleActionGate(max_audit_records=10)


def test_classify_explicit_third_party_visible_tool(gate: ExternallyVisibleActionGate) -> None:
    classification = gate.classify_tool("send_teammate_message_tool")
    assert classification.is_third_party_visible is True
    assert classification.requires_mandatory_human_review is True
    assert classification.hide_allow_always is True
    assert classification.visibility_scope == ActionVisibilityScope.THIRD_PARTY_VISIBLE
    assert "send_teammate_message_tool" in classification.rationale


def test_classify_heuristic_external_tools(gate: ExternallyVisibleActionGate) -> None:
    tools_to_test = [
        "send_email_notification",
        "post_slack_message",
        "webhook_dispatch_tool",
        "send_sms_alert",
    ]
    for tool_name in tools_to_test:
        classification = gate.classify_tool(tool_name)
        assert classification.is_third_party_visible is True
        assert classification.requires_mandatory_human_review is True
        assert classification.hide_allow_always is True
        assert classification.visibility_scope == ActionVisibilityScope.THIRD_PARTY_VISIBLE


def test_classify_user_local_tool(gate: ExternallyVisibleActionGate) -> None:
    classification = gate.classify_tool("ask_question_tool")
    assert classification.is_third_party_visible is False
    assert classification.requires_mandatory_human_review is False
    assert classification.hide_allow_always is False
    assert classification.visibility_scope == ActionVisibilityScope.USER_LOCAL


def test_classify_internal_only_tool(gate: ExternallyVisibleActionGate) -> None:
    classification = gate.classify_tool("file_read_tool")
    assert classification.is_third_party_visible is False
    assert classification.requires_mandatory_human_review is False
    assert classification.hide_allow_always is False
    assert classification.visibility_scope == ActionVisibilityScope.INTERNAL_ONLY


def test_explicit_metadata_override(gate: ExternallyVisibleActionGate) -> None:
    custom_meta = SafetyMetadata(is_third_party_visible=True)
    classification = gate.classify_tool("custom_secret_sync", explicit_metadata=custom_meta)
    assert classification.is_third_party_visible is True
    assert classification.requires_mandatory_human_review is True
    assert classification.hide_allow_always is True


def test_audit_recording_and_retrieval(gate: ExternallyVisibleActionGate) -> None:
    gate.clear_audit_records()

    record1 = gate.record_audit(
        action_id="act-1",
        session_id="sess-A",
        agent_id="agent-1",
        tool_name="send_email_tool",
        recipient_or_destination="user@example.com",
        content_preview="Project status report",
        is_approved=True,
        approved_by="admin-user",
    )
    assert record1.action_id == "act-1"
    assert record1.is_approved is True

    record2 = gate.record_audit(
        action_id="act-2",
        session_id="sess-B",
        agent_id="agent-2",
        tool_name="webhook_dispatch_tool",
        recipient_or_destination="https://api.external.com/hook",
        content_preview="Alert payload",
        is_approved=False,
    )
    assert record2.action_id == "act-2"
    assert record2.is_approved is False

    # Filter by session
    sess_a_records = gate.get_audit_records(session_id="sess-A")
    assert len(sess_a_records) == 1
    assert sess_a_records[0].action_id == "act-1"

    # All records
    all_records = gate.get_audit_records()
    assert len(all_records) == 2


def test_audit_record_capacity_pruning(gate: ExternallyVisibleActionGate) -> None:
    gate.clear_audit_records()
    # gate has max_audit_records=10
    for i in range(15):
        gate.record_audit(
            action_id=f"act-{i}",
            session_id="sess-C",
            agent_id="agent-1",
            tool_name="post_slack_message",
            recipient_or_destination="#ops",
            content_preview=f"msg {i}",
            is_approved=True,
        )

    records = gate.get_audit_records()
    assert len(records) == 10
    assert records[0].action_id == "act-5"
    assert records[-1].action_id == "act-14"
