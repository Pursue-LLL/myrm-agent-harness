# ============================================================================
# Unit Tests for BranchRunSnapshotEngine (Item 152)
# Verifies dual-branching Run forks, immutable policy snapshot inheritance,
# parent attempt preservation, active branch projection, and artifact diffs.
# ============================================================================

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.fork import (
    BranchRunSnapshotEngine,
    IntentSnapshot,
    PolicySnapshot,
    RunStatus,
)


def test_initial_run_lifecycle_and_attempts() -> None:
    """Verifies creation, attempt tracking, and completion of root BranchRun."""
    engine = BranchRunSnapshotEngine()
    policy = PolicySnapshot(
        model_name="claude-3-7-sonnet",
        temperature=0.2,
        allowed_tools=("read_file", "write_to_file", "run_command"),
        sandbox_mode="bwrap_secure",
        timeout_seconds=300,
    )
    intent = IntentSnapshot(
        user_prompt="Build user authentication module",
        objective_summary="JWT-based authentication flow with SQLite store",
    )

    run = engine.create_initial_run(
        session_id="session-user-auth",
        policy=policy,
        intent=intent,
    )

    assert run.session_id == "session-user-auth"
    assert run.parent_run_id is None
    assert run.fork_node_id is None
    assert run.status == RunStatus.RUNNING
    assert run.policy_snapshot.model_name == "claude-3-7-sonnet"
    assert engine.get_active_run("session-user-auth") == run

    # Record 2 execution attempts
    att1 = engine.record_attempt(
        run_id=run.run_id,
        tool_call_count=3,
        duration_ms=1250.0,
        status=RunStatus.RUNNING,
        thought_trace="Analyzing existing auth models",
    )
    assert att1.attempt_number == 1
    assert len(run.attempt_history) == 1

    att2 = engine.record_attempt(
        run_id=run.run_id,
        tool_call_count=5,
        duration_ms=2100.0,
        status=RunStatus.COMPLETED,
        thought_trace="Generated jwt.py and test suite",
    )
    assert att2.attempt_number == 2
    assert len(run.attempt_history) == 2

    # Finish run with produced artifacts
    finished = engine.finish_run(
        run_id=run.run_id,
        status=RunStatus.COMPLETED,
        generated_artifact_ids=["art-jwt-service", "art-auth-tests"],
    )
    assert finished.status == RunStatus.COMPLETED
    assert finished.finished_at is not None
    assert "art-jwt-service" in finished.generated_artifact_ids


def test_fork_branch_run_immutability_guarantee() -> None:
    """Verifies that forking at a historical node never corrupts parent run history."""
    engine = BranchRunSnapshotEngine()
    policy = PolicySnapshot(
        model_name="gpt-4o",
        temperature=0.5,
        allowed_tools=("bash", "python"),
    )
    intent1 = IntentSnapshot(
        user_prompt="Step 1: Create DB schema",
        objective_summary="Initial SQL schema design",
    )

    parent_run = engine.create_initial_run("session-db", policy, intent1)
    engine.record_attempt(
        run_id=parent_run.run_id,
        tool_call_count=2,
        duration_ms=800.0,
        status=RunStatus.COMPLETED,
    )
    engine.finish_run(
        run_id=parent_run.run_id,
        status=RunStatus.COMPLETED,
        generated_artifact_ids=["art-schema-v1"],
    )

    # Fork from parent_run at fork_node "msg-turn-1"
    new_intent = IntentSnapshot(
        user_prompt="Step 1 alternative: Use MongoDB instead of SQL",
        objective_summary="NoSQL alternative architecture exploration",
    )
    child_run = engine.fork_branch_run(
        parent_run_id=parent_run.run_id,
        fork_node_id="msg-turn-1",
        new_intent=new_intent,
    )

    # Strict immutability assertions on parent
    assert parent_run.status == RunStatus.COMPLETED
    assert len(parent_run.attempt_history) == 1
    assert parent_run.generated_artifact_ids == ["art-schema-v1"]

    # Child run assertions
    assert child_run.parent_run_id == parent_run.run_id
    assert child_run.fork_node_id == "msg-turn-1"
    assert child_run.status == RunStatus.PENDING
    assert child_run.intent_snapshot.user_prompt == "Step 1 alternative: Use MongoDB instead of SQL"
    # Deeply inherited policy
    assert child_run.policy_snapshot.model_name == "gpt-4o"
    assert child_run.policy_snapshot.allowed_tools == ("bash", "python")
    # Active pointer moved to child
    assert engine.get_active_run("session-db") == child_run


def test_fork_policy_override_option() -> None:
    """Verifies policy customization when branching."""
    engine = BranchRunSnapshotEngine()
    parent_policy = PolicySnapshot(model_name="claude-3-5-haiku", temperature=0.1)
    parent_intent = IntentSnapshot(user_prompt="Write draft", objective_summary="Drafting")
    parent_run = engine.create_initial_run("session-draft", parent_policy, parent_intent)

    override_policy = PolicySnapshot(
        model_name="claude-3-7-sonnet",
        temperature=0.8,
        timeout_seconds=900,
    )
    child_intent = IntentSnapshot(user_prompt="Deep rewrite", objective_summary="Creative rewrite")

    child_run = engine.fork_branch_run(
        parent_run_id=parent_run.run_id,
        fork_node_id="turn-2",
        new_intent=child_intent,
        override_policy=override_policy,
    )

    assert child_run.policy_snapshot.model_name == "claude-3-7-sonnet"
    assert child_run.policy_snapshot.temperature == 0.8
    assert child_run.policy_snapshot.timeout_seconds == 900
    assert parent_run.policy_snapshot.model_name == "claude-3-5-haiku"


def test_switch_active_branch_linear_projection() -> None:
    """Verifies active branch switching and multi-generation linear lineage reconstruction."""
    engine = BranchRunSnapshotEngine()
    policy = PolicySnapshot(model_name="qwen-2.5-coder")
    intent0 = IntentSnapshot(user_prompt="Root", objective_summary="Root task")

    run_root = engine.create_initial_run("session-tree", policy, intent0, custom_run_id="run-root")

    # Branch A: root -> A1
    intent_a = IntentSnapshot(user_prompt="Path A", objective_summary="Branch A")
    run_a = engine.fork_branch_run(
        parent_run_id="run-root",
        fork_node_id="node-0",
        new_intent=intent_a,
        custom_run_id="run-branch-a",
    )

    # Branch B: root -> B1 -> B2
    intent_b1 = IntentSnapshot(user_prompt="Path B1", objective_summary="Branch B1")
    run_b1 = engine.fork_branch_run(
        parent_run_id="run-root",
        fork_node_id="node-0",
        new_intent=intent_b1,
        custom_run_id="run-branch-b1",
    )
    intent_b2 = IntentSnapshot(user_prompt="Path B2", objective_summary="Branch B2")
    run_b2 = engine.fork_branch_run(
        parent_run_id="run-branch-b1",
        fork_node_id="node-b1",
        new_intent=intent_b2,
        custom_run_id="run-branch-b2",
    )

    # Switch to Branch A: linear projection should be [run-root, run-branch-a]
    lineage_a = engine.switch_active_branch("session-tree", "run-branch-a")
    assert [r.run_id for r in lineage_a] == ["run-root", "run-branch-a"]
    assert engine.get_active_run("session-tree") == run_a

    # Switch to Branch B2: linear projection should be [run-root, run-branch-b1, run-branch-b2]
    lineage_b = engine.switch_active_branch("session-tree", "run-branch-b2")
    assert [r.run_id for r in lineage_b] == ["run-root", "run-branch-b1", "run-branch-b2"]
    assert engine.get_active_run("session-tree") == run_b2

    # Switch back to Root
    lineage_root = engine.switch_active_branch("session-tree", "run-root")
    assert [r.run_id for r in lineage_root] == ["run-root"]

    # Invalid session run switch
    with pytest.raises(ValueError):
        engine.switch_active_branch("other-session", "run-root")


def test_compare_branch_artifacts() -> None:
    """Verifies cross-branch artifact mutation detection (ADDED, REMOVED, MODIFIED)."""
    engine = BranchRunSnapshotEngine()
    policy = PolicySnapshot(model_name="deepseek-v3")
    intent = IntentSnapshot(user_prompt="Test", objective_summary="Test")

    run_a = engine.create_initial_run("sess-art", policy, intent, custom_run_id="run-a")
    engine.finish_run(
        run_id="run-a",
        status=RunStatus.COMPLETED,
        generated_artifact_ids=["common-doc", "old-config"],
    )

    run_b = engine.fork_branch_run(
        parent_run_id="run-a",
        fork_node_id="node-1",
        new_intent=IntentSnapshot(user_prompt="Alt", objective_summary="Alt"),
        custom_run_id="run-b",
    )
    engine.finish_run(
        run_id="run-b",
        status=RunStatus.COMPLETED,
        generated_artifact_ids=["common-doc", "new-feature"],
    )

    # Provide content hash/text mapping
    contents = {
        "run-a:common-doc": "content-v1",
        "run-b:common-doc": "content-v2",  # MODIFIED
    }

    comparison = engine.compare_branch_artifacts(
        source_run_id="run-a",
        target_run_id="run-b",
        artifact_contents=contents,
    )

    assert comparison.source_run_id == "run-a"
    assert comparison.target_run_id == "run-b"
    assert comparison.common_artifact_count == 1

    diff_types = {d.artifact_id: d.change_type for d in comparison.divergent_artifacts}
    assert diff_types["old-config"] == "REMOVED"
    assert diff_types["new-feature"] == "ADDED"
    assert diff_types["common-doc"] == "MODIFIED"


def test_branch_run_types_serialization() -> None:
    """Verifies that all branch run dataclasses cleanly serialize to dictionary."""
    policy = PolicySnapshot(model_name="o3-mini", custom_flags=(("flag1", "val1"),))
    pol_dict = policy.to_dict()
    assert pol_dict["model_name"] == "o3-mini"
    assert pol_dict["custom_flags"] == [["flag1", "val1"]]

    intent = IntentSnapshot(user_prompt="hi", objective_summary="hello")
    int_dict = intent.to_dict()
    assert int_dict["user_prompt"] == "hi"

    engine = BranchRunSnapshotEngine()
    run = engine.create_initial_run("sess-dict", policy, intent)
    run_dict = run.to_dict()
    assert run_dict["session_id"] == "sess-dict"
    assert run_dict["status"] == "running"
