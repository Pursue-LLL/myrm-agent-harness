"""Tests for integration retained context purge and provenance revocation suite.

[INPUT]
- pytest
- datetime::{UTC, datetime}
- myrm_agent_harness.toolkits.memory.integration_purge::{
    IntegrationRetainedContextManager,
    IntegrationRetainedContextSummary,
    ProvenanceRevocationRecord,
    PurgeExecutionMode,
    PurgeExecutionResult,
    create_integration_context_purge_tool,
  }
- myrm_agent_harness.toolkits.memory import MemoryManager

[OUTPUT]
- Unit tests verifying retention inspection, selective purge, Dots parity,
  tamper-evident provenance revocation ledger, and agent runtime tool execution.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from myrm_agent_harness.toolkits.memory.integration_purge import (
    IntegrationRetainedContextManager,
    IntegrationRetainedContextSummary,
    PurgeExecutionMode,
    PurgeExecutionResult,
    create_integration_context_purge_tool,
)


@pytest.mark.asyncio
async def test_retained_context_inspection_with_mock_records() -> None:
    """Test inspecting retained context items with simulated storage records."""
    manager = IntegrationRetainedContextManager()
    t1 = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
    t2 = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)

    manager.register_mock_record("google_workspace", "Meeting notes about Q4 targets", t1)
    manager.register_mock_record("google_workspace", "Email thread on budget approval", t2)

    summary: IntegrationRetainedContextSummary = await manager.inspect_retained_context(
        "google_workspace",
        provider_type="oauth_provider",
    )

    assert summary.integration_id == "google_workspace"
    assert summary.provider_type == "oauth_provider"
    assert summary.retained_memory_count == 2
    assert summary.total_retained_items == 2
    assert len(summary.sample_snippets) == 2
    assert summary.oldest_retained_at == t1
    assert summary.latest_retained_at == t2
    assert summary.is_provenance_revoked is False


@pytest.mark.asyncio
async def test_retain_context_mode_preserves_data() -> None:
    """Test RETAIN_CONTEXT mode (Dots parity): disconnects but retains data."""
    manager = IntegrationRetainedContextManager()
    manager.register_mock_record("github", "PR review comments for auth feature")

    result: PurgeExecutionResult = await manager.execute_purge(
        "github",
        PurgeExecutionMode.RETAIN_CONTEXT,
    )

    assert result.success is True
    assert result.mode == PurgeExecutionMode.RETAIN_CONTEXT
    assert result.deleted_memories_count == 0
    assert result.deleted_trees_count == 0
    assert result.revocation_id is None
    assert manager.is_provenance_revoked("github") is False

    # Check that data is still retained
    summary = await manager.inspect_retained_context("github")
    assert summary.total_retained_items == 1


@pytest.mark.asyncio
async def test_purge_and_revoke_mode_removes_data_and_revokes_provenance() -> None:
    """Test PURGE_AND_REVOKE mode: cleans up data and records revocation in ledger."""
    deleted_calls: list[tuple[str, str]] = []

    async def mock_delete_cb(key: str, val: str) -> dict[str, int]:
        deleted_calls.append((key, val))
        return {"semantic": 3, "episodic": 2}

    async def mock_remove_trees_cb(integration_id: str) -> int:
        return 1

    def mock_count_trees_cb(integration_id: str) -> int:
        return 1

    manager = IntegrationRetainedContextManager(
        delete_memories_callback=mock_delete_cb,
        remove_trees_callback=mock_remove_trees_cb,
        count_trees_callback=mock_count_trees_cb,
    )
    manager.register_mock_record("slack", "Team daily sync transcript snippet")

    # Initial inspection
    summary_before = await manager.inspect_retained_context("slack")
    assert summary_before.retained_tree_count == 1
    assert summary_before.is_provenance_revoked is False

    # Execute purge & revoke
    result = await manager.execute_purge(
        "slack",
        PurgeExecutionMode.PURGE_AND_REVOKE,
        actor="security_admin",
        reason="GDPR right to be forgotten request",
    )

    assert result.success is True
    assert result.mode == PurgeExecutionMode.PURGE_AND_REVOKE
    # 5 from delete_cb * 2 keys ("provenance", "integration_id") = 10, plus 1 mock record = 11
    assert result.deleted_memories_count == 11
    assert result.deleted_trees_count == 1
    assert result.revocation_id is not None
    assert manager.is_provenance_revoked("slack") is True

    # Audit ledger verification
    ledger = manager.list_revocation_records()
    assert len(ledger) == 1
    record = ledger[0]
    assert record.integration_id == "slack"
    assert record.actor == "security_admin"
    assert "GDPR" in record.reason
    assert record.purged_items_count == 12

    # Verify unrevoking / reinstating provenance
    reinstated = manager.unrevoke_provenance("slack")
    assert reinstated is True
    assert manager.is_provenance_revoked("slack") is False


@pytest.mark.asyncio
async def test_agent_runtime_tool_execution() -> None:
    """Test LangChain tool execution for agent autonomy in inspecting and purging."""
    manager = IntegrationRetainedContextManager()
    manager.register_mock_record("jira", "Issue PROJ-101 details and user requirements")

    tool = create_integration_context_purge_tool(manager)

    # 1. Action: inspect
    inspect_output = await tool.ainvoke({
        "action": "inspect",
        "integration_id": "jira",
    })
    assert "Connector 'jira' Retained Context Summary:" in inspect_output
    assert "Total Retained Items: 1" in inspect_output
    assert "Provenance Status: ACTIVE" in inspect_output

    # 2. Action: status
    status_output = await tool.ainvoke({
        "action": "status",
        "integration_id": "jira",
    })
    assert "ACTIVE (Trusted)" in status_output

    # 3. Action: purge with purge_and_revoke
    purge_output = await tool.ainvoke({
        "action": "purge",
        "integration_id": "jira",
        "purge_mode": "purge_and_revoke",
        "reason": "De-authorizing Jira integration",
    })
    assert "Purge Result for 'jira':" in purge_output
    assert "Deleted Memories: 1" in purge_output
    assert "STATUS: SUCCESS" in purge_output.upper()

    # 4. Status after revocation
    status_output_after = await tool.ainvoke({
        "action": "status",
        "integration_id": "jira",
    })
    assert "REVOKED" in status_output_after
