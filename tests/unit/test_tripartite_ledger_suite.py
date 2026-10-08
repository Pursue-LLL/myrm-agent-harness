"""Unit test suite for Tripartite Isolation & Immutable Audit Ledger."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.tripartite_ledger import (
    GENESIS_PREV_HASH,
    ActionExecutionResult,
    ActionSemanticMode,
    ActionSemanticsGuard,
    ActionSemanticViolationError,
    AuditEvidenceRecord,
    PreIOAuditAssertionError,
    TripartiteAuditLedger,
    ZeroKnowledgeOpsController,
)


def test_append_record_and_hash_chain() -> None:
    """Test appending records and maintaining cryptographic hash chain."""
    ledger = TripartiteAuditLedger()

    rec1 = ledger.append_record(
        who_user_id="user-alice",
        who_agent_id="agent-coder",
        rule_version_hash="sha256-gov-v1",
        tool_name="mcp__github__create_issue",
        tool_args={"repo": "Pursue-LLL/myrm-agent", "auth_token": "ghp_secret_123"},
        connector_source="mcp__github",
        connector_scope="issues:write",
        authorized_parameters=["repo"],
        reconcile_receipt="receipt-issue-101",
    )

    assert rec1.sequence_number == 0
    assert rec1.prev_hash == GENESIS_PREV_HASH
    assert rec1.sanitized_args_snapshot["auth_token"] == "[REDACTED_SECRET]"
    assert rec1.sanitized_args_snapshot["repo"] == "Pursue-LLL/myrm-agent"

    rec2 = ledger.append_record(
        who_user_id="user-bob",
        who_agent_id="agent-reviewer",
        rule_version_hash="sha256-gov-v1",
        tool_name="mcp__github__add_comment",
        tool_args={"issue_id": 101, "comment": "Approved"},
        connector_source="mcp__github",
        connector_scope="issues:write",
        authorized_parameters=["issue_id", "comment"],
        reconcile_receipt="receipt-comment-202",
    )

    assert rec2.sequence_number == 1
    assert rec2.prev_hash == rec1.record_hash

    # Verify chain
    verification = ledger.verify_chain()
    assert verification.is_valid is True
    assert verification.total_records == 2


def test_tamper_detection() -> None:
    """Test that any tampering in the ledger chain is flagged immediately."""
    ledger = TripartiteAuditLedger()

    ledger.append_record(
        who_user_id="user-1",
        who_agent_id="agent-1",
        rule_version_hash="v1",
        tool_name="read_file",
        tool_args={"path": "main.py"},
        connector_source="filesystem",
        connector_scope="read",
        authorized_parameters=["path"],
        reconcile_receipt="rcpt-1",
    )
    ledger.append_record(
        who_user_id="user-1",
        who_agent_id="agent-1",
        rule_version_hash="v1",
        tool_name="write_file",
        tool_args={"path": "main.py"},
        connector_source="filesystem",
        connector_scope="write",
        authorized_parameters=["path"],
        reconcile_receipt="rcpt-2",
    )

    # Tamper with record 1 payload by replacing it
    tampered_rec = AuditEvidenceRecord(
        record_id=ledger._records[0].record_id,
        sequence_number=ledger._records[0].sequence_number,
        prev_hash=ledger._records[0].prev_hash,
        record_hash=ledger._records[0].record_hash,
        who_user_id="attacker",
        who_agent_id=ledger._records[0].who_agent_id,
        when_timestamp=ledger._records[0].when_timestamp,
        rule_version_hash=ledger._records[0].rule_version_hash,
        tool_name=ledger._records[0].tool_name,
        tool_call_args_hash=ledger._records[0].tool_call_args_hash,
        sanitized_args_snapshot=ledger._records[0].sanitized_args_snapshot,
        connector_source=ledger._records[0].connector_source,
        connector_scope=ledger._records[0].connector_scope,
        authorized_parameters_hash=ledger._records[0].authorized_parameters_hash,
        reconcile_receipt=ledger._records[0].reconcile_receipt,
    )
    ledger._records[0] = tampered_rec

    verification = ledger.verify_chain()
    assert verification.is_valid is False
    assert verification.corrupted_record_id == tampered_rec.record_id
    assert "tamper detected" in (verification.reason or "")


def test_query_records() -> None:
    """Test querying records by connector source, tool, and agent."""
    ledger = TripartiteAuditLedger()
    ledger.append_record(
        who_user_id="u1",
        who_agent_id="agent-a",
        rule_version_hash="v1",
        tool_name="read_data",
        tool_args={},
        connector_source="mcp__db",
        connector_scope="read",
        authorized_parameters=[],
        reconcile_receipt="rc-1",
    )
    ledger.append_record(
        who_user_id="u1",
        who_agent_id="agent-b",
        rule_version_hash="v1",
        tool_name="write_data",
        tool_args={},
        connector_source="mcp__db",
        connector_scope="write",
        authorized_parameters=[],
        reconcile_receipt="rc-2",
    )

    db_records = ledger.query_records(connector_source="mcp__db")
    assert len(db_records) == 2

    agent_b_records = ledger.query_records(who_agent_id="agent-b")
    assert len(agent_b_records) == 1
    assert agent_b_records[0].tool_name == "write_data"


def test_action_semantics_replay_log_forbidden() -> None:
    """Test that REPLAY_LOG strictly rejects any external tool execution."""
    ledger = TripartiteAuditLedger()
    guard = ActionSemanticsGuard(ledger)

    with pytest.raises(ActionSemanticViolationError, match="REPLAY_LOG mode strictly forbids"):
        guard.execute_action(
            mode=ActionSemanticMode.REPLAY_LOG,
            tool_name="send_payment",
            executor=lambda: "paid",
        )


def test_action_semantics_offline_eval_mocking() -> None:
    """Test that OFFLINE_EVAL permits read-only tools but mocks side-effect tools."""
    ledger = TripartiteAuditLedger()
    guard = ActionSemanticsGuard(ledger)

    # Read-only tool
    res_read = guard.execute_action(
        mode=ActionSemanticMode.OFFLINE_EVAL,
        tool_name="read_report",
        executor=lambda: "report content",
    )
    assert res_read.executed is True
    assert res_read.is_simulated is False
    assert res_read.result == "report content"

    # Side-effect tool
    res_write = guard.execute_action(
        mode=ActionSemanticMode.OFFLINE_EVAL,
        tool_name="create_order",
        executor=lambda: "order created",
    )
    assert res_write.executed is False
    assert res_write.is_simulated is True
    assert "[MOCK_SIMULATION]" in res_write.result


def test_action_semantics_re_execute_assertions() -> None:
    """Test RE_EXECUTE explicit confirmation and pre-I/O audit persistence assertion."""
    ledger = TripartiteAuditLedger()
    guard = ActionSemanticsGuard(ledger)

    # 1. Unconfirmed re-execute rejected
    with pytest.raises(ActionSemanticViolationError, match="requires explicit operator confirmation"):
        guard.execute_action(
            mode=ActionSemanticMode.RE_EXECUTE,
            tool_name="send_payment",
            executor=lambda: "success",
            explicit_confirmed=False,
        )

    # 2. Confirmed but unrecorded audit record rejected
    with pytest.raises(PreIOAuditAssertionError, match="must be committed to Immutable Audit Ledger"):
        guard.execute_action(
            mode=ActionSemanticMode.RE_EXECUTE,
            tool_name="send_payment",
            executor=lambda: "success",
            audit_record_id="aud-non-existent",
            explicit_confirmed=True,
        )

    # 3. Pre-recorded audit record passes gate
    record = ledger.append_record(
        who_user_id="user-c",
        who_agent_id="agent-executor",
        rule_version_hash="v1",
        tool_name="send_payment",
        tool_args={"amount": 500},
        connector_source="banking_api",
        connector_scope="transfers",
        authorized_parameters=["amount"],
        reconcile_receipt="pending",
    )

    res: ActionExecutionResult = guard.execute_action(
        mode=ActionSemanticMode.RE_EXECUTE,
        tool_name="send_payment",
        executor=lambda: "tx-success-500",
        audit_record_id=record.record_id,
        explicit_confirmed=True,
    )
    assert res.executed is True
    assert res.is_simulated is False
    assert res.result == "tx-success-500"


def test_zero_knowledge_ops_control() -> None:
    """Test zero-knowledge telemetry and force stop without content exposure."""
    ops = ZeroKnowledgeOpsController()
    ops.register_task(task_id="task-42", agent_id="agent-analyst", memory_bytes=2048000)

    telemetry = ops.get_telemetry("task-42")
    assert telemetry.task_id == "task-42"
    assert telemetry.agent_id == "agent-analyst"
    assert telemetry.state == "RUNNING"
    assert telemetry.memory_bytes == 2048000

    # Ensure no payload or business text exists in telemetry
    assert not hasattr(telemetry, "user_prompt")
    assert not hasattr(telemetry, "content")

    # Ops force-stop
    stopped = ops.force_stop("task-42", operator_id="ops-admin-1")
    assert stopped is True
    updated_telemetry = ops.get_telemetry("task-42")
    assert updated_telemetry.state == "STOPPED_BY_OPS"
