"""
[INPUT]: AgentRuntimeCausalityTracker routines, process hierarchy nodes, and mock failure events.
[OUTPUT]: Pytest suite validating agent causality trees, orphan process cascade reaping, deadlock polling breaker, and post-mortem traces.
[POS]: myrm-agent-harness/tests/observability/test_runtime_zombie_reaper.py
"""

import time
import pytest
from myrm_agent_harness.observability.runtime_zombie_reaper import (
    AgentRuntimeCausalityTracker,
    PostMortemTaskEntry,
    ProcessCausalityNode,
    ProcessLifecycleState,
)


@pytest.fixture
def tracker() -> AgentRuntimeCausalityTracker:
    t = AgentRuntimeCausalityTracker()
    t.reset()
    return t


def test_process_causality_tree_and_orphan_reaping(tracker: AgentRuntimeCausalityTracker) -> None:
    now_ms = int(time.time() * 1000)

    # 1. Primary agent (parent)
    primary = ProcessCausalityNode(
        node_id="sess_root_001",
        name="MainAssistant",
        role="primary_agent",
        pid=1001,
        pgid=1001,
        profile_id="dev_profile",
        state=ProcessLifecycleState.RUNNING,
        cpu_percent=12.5,
        memory_rss_mb=210.0,
        tokens_consumed=5000,
        last_heartbeat_ms=now_ms,
    )
    tracker.upsert_node(primary)

    # 2. Delegated subagent (child of primary)
    subagent = ProcessCausalityNode(
        node_id="sub_task_002",
        name="CodingAgent",
        role="subagent",
        pid=1002,
        pgid=1002,
        parent_id="sess_root_001",
        profile_id="dev_profile",
        state=ProcessLifecycleState.RUNNING,
        cpu_percent=45.0,
        memory_rss_mb=320.0,
        tokens_consumed=12000,
        last_heartbeat_ms=now_ms,
    )
    tracker.upsert_node(subagent)

    # 3. Auxiliary helper process (child of subagent, e.g. Playwright browser)
    helper = ProcessCausalityNode(
        node_id="helper_proc_003",
        name="PlaywrightBrowser",
        role="helper_process",
        pid=1003,
        pgid=1002,  # Bound to subagent's process group
        parent_id="sub_task_002",
        profile_id="dev_profile",
        state=ProcessLifecycleState.RUNNING,
        cpu_percent=85.0,
        memory_rss_mb=450.0,
        tokens_consumed=0,
        last_heartbeat_ms=now_ms,
    )
    tracker.upsert_node(helper)

    # Verify initial snapshot
    snap1 = tracker.get_snapshot()
    assert len(snap1.nodes) == 3
    assert len(snap1.profile_summaries) == 1
    assert snap1.profile_summaries[0].active_nodes_count == 3
    assert snap1.profile_summaries[0].total_cpu_percent == 142.5

    # 4. Trigger cascading orphan reap on primary agent detachment
    reaped = tracker.reap_orphans("sess_root_001", reason="Primary session user closed tab")
    assert "sub_task_002" in reaped
    assert "helper_proc_003" in reaped
    assert len(reaped) == 2

    # Verify that child processes are now terminated with exit code -15 (SIGTERM)
    sub_node = tracker.get_node("sub_task_002")
    helper_node = tracker.get_node("helper_proc_003")
    assert sub_node is not None and sub_node.state == ProcessLifecycleState.TERMINATED
    assert sub_node.exit_code == -15
    assert helper_node is not None and helper_node.state == ProcessLifecycleState.TERMINATED
    assert helper_node.exit_code == -15

    snap2 = tracker.get_snapshot()
    assert snap2.total_reaped_orphans == 2


def test_deadlock_polling_breaker(tracker: AgentRuntimeCausalityTracker) -> None:
    now_ms = int(time.time() * 1000)

    # Child subagent crashes with OOM
    crashed_child = ProcessCausalityNode(
        node_id="child_worker_oom",
        name="HeavyWorker",
        role="subagent",
        pid=2001,
        pgid=2001,
        parent_id="parent_master",
        profile_id="prod_profile",
        state=ProcessLifecycleState.CRASHED,
        cpu_percent=0.0,
        memory_rss_mb=0.0,
        tokens_consumed=800,
        last_heartbeat_ms=now_ms,
        exit_code=137,
        crash_reason="Container OOM Killed (SIGKILL 137)",
    )
    tracker.upsert_node(crashed_child)

    # Parent polls child -> breaker must trip to prevent infinite hang
    is_deadlocked, fault_msg = tracker.check_deadlock_polling("parent_master", "child_worker_oom")
    assert is_deadlocked is True
    assert fault_msg is not None
    assert "Container OOM Killed" in fault_msg

    # Missing non-existent child also trips breaker
    is_deadlocked_ghost, ghost_msg = tracker.check_deadlock_polling("parent_master", "ghost_child_missing")
    assert is_deadlocked_ghost is True
    assert ghost_msg is not None
    assert "disappeared completely" in ghost_msg


def test_post_mortem_and_reset(tracker: AgentRuntimeCausalityTracker) -> None:
    now_ms = int(time.time() * 1000)

    tracker.record_failed_task(
        PostMortemTaskEntry(
            task_id="task_fail_99",
            name="DeepResearchBatch",
            parent_task_id="root_sess",
            profile_id="research_team",
            exit_code=1,
            crash_reason="RateLimitExceeded: OpenAI API quota exhausted",
            duration_ms=45000,
            terminated_at_ms=now_ms,
        )
    )

    snap = tracker.get_snapshot()
    assert len(snap.recent_failed_tasks) == 1
    assert snap.recent_failed_tasks[0].task_id == "task_fail_99"

    # Reset
    tracker.reset()
    snap_after = tracker.get_snapshot()
    assert len(snap_after.nodes) == 0
    assert len(snap_after.recent_failed_tasks) == 0
    assert snap_after.total_reaped_orphans == 0
