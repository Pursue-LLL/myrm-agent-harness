"""Unit tests for In-Flight Policy Snapshot Pinning & Non-Silent Drift Suite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.policy_snapshot import (
    EmergencyHotKillBlockedError,
    PolicyDriftViolationError,
    PolicySnapshotManager,
)


def test_initial_snapshot_and_in_flight_pinning() -> None:
    """Test creating snapshots and pinning policy to in-flight task."""
    manager = PolicySnapshotManager(
        initial_prompt_template="System Prompt v1",
        initial_allowed_tools=["read_file", "search_web"],
        initial_governance_rules={"max_file_size_mb": 10},
    )

    assert manager.active_snapshot.version_number == 1
    assert manager.total_snapshots == 1

    # Pin to task-1
    snap_t1 = manager.bind_task_policy("task-1")
    assert snap_t1.version_number == 1
    assert snap_t1.allowed_tools == ("read_file", "search_web")

    # Calling bind again returns identical pinned snapshot
    assert manager.bind_task_policy("task-1") == snap_t1


def test_soft_update_shields_in_flight_tasks() -> None:
    """Test Track A Soft Update: new policy affects new tasks, but in-flight tasks stay pinned."""
    manager = PolicySnapshotManager(
        initial_prompt_template="System Prompt v1",
        initial_allowed_tools=["read_file"],
    )

    # In-flight task binds to v1
    snap_t1 = manager.bind_task_policy("task-1")
    assert snap_t1.version_number == 1

    # In-flight task can execute read_file
    manager.assert_tool_execution_allowed("task-1", "read_file")

    # Admin updates policy (Track A: Soft Update) adding new_fancy_tool
    snap_v2 = manager.apply_soft_update(
        new_prompt_template="System Prompt v2",
        new_allowed_tools=["read_file", "new_fancy_tool"],
    )
    assert snap_v2.version_number == 2
    assert manager.active_snapshot.version_number == 2

    # In-flight task-1 is still pinned to v1! It is NOT permitted to use new_fancy_tool
    with pytest.raises(PolicyDriftViolationError, match="not permitted by pinned policy snapshot"):
        manager.assert_tool_execution_allowed("task-1", "new_fancy_tool")

    # Newly initiated task-2 binds to v2 and CAN execute new_fancy_tool
    manager.bind_task_policy("task-2")
    manager.assert_tool_execution_allowed("task-2", "new_fancy_tool")


def test_emergency_hot_kill_immediately_blocks_in_flight_tasks() -> None:
    """Test Track B Emergency Hot Kill: immediately halts high-risk tool in-flight."""
    manager = PolicySnapshotManager(
        initial_allowed_tools=["read_file", "bash_exec"],
    )

    manager.bind_task_policy("task-long-running")
    manager.assert_tool_execution_allowed("task-long-running", "bash_exec")

    # Admin issues emergency hot-kill
    directive = manager.apply_emergency_hot_kill(
        revoked_tools=["bash_exec"],
        reason="Zero-day RCE identified in bash tool",
    )
    assert directive.is_active is True

    # In-flight task is immediately blocked!
    with pytest.raises(EmergencyHotKillBlockedError, match="blocked by active emergency hot-kill"):
        manager.assert_tool_execution_allowed("task-long-running", "bash_exec")

    # Allowed tools like read_file remain unblocked
    manager.assert_tool_execution_allowed("task-long-running", "read_file")

    # Revoking the directive restores execution
    manager.revoke_emergency_hot_kill(directive.directive_id)
    manager.assert_tool_execution_allowed("task-long-running", "bash_exec")
