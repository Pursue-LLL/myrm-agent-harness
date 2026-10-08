"""Unit tests for AppendOnlySessionTreeDagAndExplorationBranchingSuite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management import (
    DagEntryKind,
    SessionTreeDagReceipt,
    SessionTreeDagSuite,
    SessionTreeEntry,
)


def test_immutable_tree_dag_append_and_lineage_isolation(tmp_path: pytest.TempPathFactory) -> None:
    """Test append-only immutable nodes with explicit parentId and linear lineage reconstruction."""
    jsonl_file = str(tmp_path / "session_tree.jsonl")  # type: ignore[operator]
    suite = SessionTreeDagSuite(session_id="sess-tree-001", persistence_file_path=jsonl_file)

    msg1 = suite.append_message(role="user", content="Deploy v1.0.0 to staging")
    msg2 = suite.append_message(role="assistant", content="Running deployment pipeline...")
    msg3 = suite.append_message(role="system", content="Pipeline succeeded on worker-3")

    assert msg1.parent_id is None
    assert msg2.parent_id == msg1.entry_id
    assert msg3.parent_id == msg2.entry_id

    lineage = suite.get_active_lineage_path()
    assert len(lineage) == 3
    assert [e.entry_id for e in lineage] == [msg1.entry_id, msg2.entry_id, msg3.entry_id]

    # Verify JSONL lines written to disk
    storage = suite.get_storage()
    assert len(storage.get_raw_jsonl_lines()) == 3


def test_first_class_state_switch_entries() -> None:
    """Test that model switch, thinking level adjustment, and compaction are first-class DAG entries."""
    suite = SessionTreeDagSuite(session_id="sess-switch-002")

    msg = suite.append_message(role="user", content="Analyze complex algorithm")
    model_evt = suite.append_model_switch(
        model_name="claude-3-7-sonnet",
        provider="anthropic",
        reason="Switching to reasoning model for deep analysis",
    )
    think_evt = suite.append_thinking_level_switch(level="high", budget_tokens=8192)
    compact_evt = suite.append_compaction_snapshot(
        summary_text="Prior architecture discussion summarized",
        compacted_up_to_entry_id=msg.entry_id,
    )

    assert model_evt.kind == DagEntryKind.MODEL_SWITCH
    assert model_evt.payload["model_name"] == "claude-3-7-sonnet"
    assert model_evt.payload["provider"] == "anthropic"

    assert think_evt.kind == DagEntryKind.THINKING_LEVEL_SWITCH
    assert think_evt.payload["budget_tokens"] == "8192"

    assert compact_evt.kind == DagEntryKind.COMPACTION_SNAPSHOT
    assert compact_evt.payload["compacted_up_to_entry_id"] == msg.entry_id

    lineage = suite.get_active_lineage_path()
    assert len(lineage) == 4
    assert lineage[-1].entry_id == compact_evt.entry_id


def test_exploration_branching_and_zero_pollution_time_travel() -> None:
    """Test forking exploratory branches from historical nodes and zero context pollution on trunk."""
    suite = SessionTreeDagSuite(session_id="sess-branch-003")

    # Step 1: Base trunk interaction
    n1 = suite.append_message(role="user", content="Task: Implement caching layer")
    n2 = suite.append_message(role="assistant", content="Consider Redis or In-Memory LRU")

    # Step 2: Fork branch A for experimental Redis cluster
    branch_redis = suite.fork_branch(new_branch_name="experiment-redis", from_entry_id=n2.entry_id)
    assert branch_redis.branch_name == "experiment-redis"
    assert branch_redis.fork_from_entry_id == n2.entry_id

    # Switch to redis branch and perform exploratory work
    suite.switch_active_branch("experiment-redis")
    r1 = suite.append_message(role="assistant", content="Attempting Redis cluster setup...")
    r2 = suite.append_message(role="system", content="Error: Redis cluster connection timed out!")

    redis_lineage = suite.get_active_lineage_path()
    assert len(redis_lineage) == 4
    assert [e.entry_id for e in redis_lineage] == [n1.entry_id, n2.entry_id, r1.entry_id, r2.entry_id]

    # Step 3: Switch back to main trunk (Zero Pollution Time-Travel)
    suite.switch_active_branch("main")
    main_lineage_before = suite.get_active_lineage_path()
    assert len(main_lineage_before) == 2
    assert [e.entry_id for e in main_lineage_before] == [n1.entry_id, n2.entry_id]

    # Main trunk proceeds with LRU instead, completely unpolluted by Redis cluster crash
    n3 = suite.append_message(role="assistant", content="Redis failed in testing, using local LRU cache.")
    main_lineage_after = suite.get_active_lineage_path()
    assert len(main_lineage_after) == 3
    assert [e.entry_id for e in main_lineage_after] == [n1.entry_id, n2.entry_id, n3.entry_id]

    # Verify that the failed Redis error never appears in main lineage
    contents = [e.payload["content"] for e in main_lineage_after]
    assert "Error: Redis cluster connection timed out!" not in contents


def test_dag_visualization_and_integrity_receipt() -> None:
    """Test generating Mermaid DAG visualization, topology graph, and cryptographic DAG receipt."""
    suite = SessionTreeDagSuite(session_id="sess-viz-004")

    n1 = suite.append_message(role="user", content="Start project")
    n2 = suite.append_message(role="assistant", content="Project started")

    suite.fork_branch("feature-b", from_entry_id=n2.entry_id)
    suite.switch_active_branch("feature-b")
    fb1 = suite.append_message(role="assistant", content="Feature B experiment")

    # Topology adjacency
    adj = suite.export_topology_graph()
    assert "ROOT" in adj
    assert adj["ROOT"] == [n1.entry_id]
    assert adj[n1.entry_id] == [n2.entry_id]
    assert adj[n2.entry_id] == [fb1.entry_id]

    # Mermaid DAG diagram
    mermaid_text = suite.generate_mermaid_dag()
    assert "graph TD" in mermaid_text
    assert f"{n1.entry_id} --> {n2.entry_id}" in mermaid_text
    assert f"{n2.entry_id} --> {fb1.entry_id}" in mermaid_text

    # Receipt
    receipt = suite.issue_dag_receipt()
    assert isinstance(receipt, SessionTreeDagReceipt)
    assert receipt.session_id == "sess-viz-004"
    assert receipt.total_entries_count == 3
    assert receipt.branches_count == 2
    assert receipt.active_branch_name == "feature-b"
    assert receipt.linear_path_entries_count == 3
    assert len(receipt.dag_hash) == 16
