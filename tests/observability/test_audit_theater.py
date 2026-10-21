"""
[INPUT]: DataAccessLedgerBuilder, ResourceAccessKind, ResourceAccessMode.
[OUTPUT]: Pytest test cases verifying lie-immune resource categorization, tool inference, timeline events, and SHA-256 integrity digest.
[POS]: myrm-agent-harness/tests/observability/test_audit_theater.py
"""

import pytest
from myrm_agent_harness.observability.audit_theater import (
    DataAccessLedgerBuilder,
    ResourceAccessKind,
    ResourceAccessMode,
    SessionDataAccessLedger,
)


@pytest.fixture
def builder() -> DataAccessLedgerBuilder:
    b = DataAccessLedgerBuilder()
    b.reset()
    return b


def test_explicit_resource_logging_and_counts(builder: DataAccessLedgerBuilder) -> None:
    session_id = "sess-audit-1"

    builder.record_resource_access(
        session_id=session_id,
        resource_id="/workspace/src/app.py",
        kind=ResourceAccessKind.FILE,
        mode=ResourceAccessMode.READ,
        scope_detail="lines 1-50",
    )
    builder.record_resource_access(
        session_id=session_id,
        resource_id="/workspace/src/output.txt",
        kind=ResourceAccessKind.FILE,
        mode=ResourceAccessMode.WRITE,
        scope_detail="write 120 lines",
    )
    builder.record_resource_access(
        session_id=session_id,
        resource_id="memory://user_preferences",
        kind=ResourceAccessKind.MEMORY,
        mode=ResourceAccessMode.READ,
    )
    builder.record_resource_access(
        session_id=session_id,
        resource_id="https://api.github.com/repos",
        kind=ResourceAccessKind.WEB_NETWORK,
        mode=ResourceAccessMode.READ,
    )

    ledger: SessionDataAccessLedger = builder.build_session_ledger(session_id)

    assert ledger.session_id == session_id
    assert ledger.total_resources_accessed == 4
    assert ledger.total_files_read == 1
    assert ledger.total_files_written == 1
    assert ledger.total_memories_queried == 1
    assert ledger.total_network_domains_visited == 1
    assert ledger.lie_immune_verified is True
    assert len(ledger.digest_sha256) == 64


def test_tool_invocation_inference(builder: DataAccessLedgerBuilder) -> None:
    session_id = "sess-tool-infer"

    # view_file -> File READ
    e1 = builder.record_tool_invocation_inference(
        session_id=session_id,
        tool_name="view_file",
        tool_args={"AbsolutePath": "/data/main.rs", "StartLine": "10", "EndLine": "40"},
    )
    assert e1 is not None
    assert e1.kind == ResourceAccessKind.FILE
    assert e1.mode == ResourceAccessMode.READ
    assert "lines 10-40" in e1.scope_detail

    # write_to_file -> File WRITE
    e2 = builder.record_tool_invocation_inference(
        session_id=session_id,
        tool_name="write_to_file",
        tool_args={"TargetFile": "/data/main.rs"},
    )
    assert e2 is not None
    assert e2.kind == ResourceAccessKind.FILE
    assert e2.mode == ResourceAccessMode.WRITE

    # call_mcp_tool -> Connector MCP
    e3 = builder.record_tool_invocation_inference(
        session_id=session_id,
        tool_name="call_mcp_tool",
        tool_args={"ServerName": "sqlite-mcp", "ToolName": "query"},
    )
    assert e3 is not None
    assert e3.kind == ResourceAccessKind.CONNECTOR_MCP
    assert "mcp://sqlite-mcp/query" == e3.resource_id


def test_timeline_events_and_plan_declarations(builder: DataAccessLedgerBuilder) -> None:
    session_id = "sess-timeline"

    builder.record_timeline_event(
        session_id=session_id,
        step_name="Planned Code Refactoring",
        tool_name="replace_file_content",
        is_plan=True,
        inputs_summary="Target: refactor auth module",
    )
    builder.record_timeline_event(
        session_id=session_id,
        step_name="Executed Code Refactoring",
        tool_name="replace_file_content",
        is_plan=False,
        status="completed",
        duration_ms=45,
    )

    ledger = builder.build_session_ledger(session_id)
    assert len(ledger.events) == 2
    assert ledger.events[0].is_plan is True
    assert ledger.events[1].is_plan is False
    assert ledger.events[1].duration_ms == 45


def test_reset_and_isolation(builder: DataAccessLedgerBuilder) -> None:
    builder.record_resource_access("s1", "/test.py", ResourceAccessKind.FILE, ResourceAccessMode.READ)
    assert builder.build_session_ledger("s1").total_resources_accessed == 1

    builder.reset()
    assert builder.build_session_ledger("s1").total_resources_accessed == 0
