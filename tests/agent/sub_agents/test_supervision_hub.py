"""Tests for Subagent Supervision Hub coordinator, transcript buffers, and actions.

[INPUT]
- myrm_agent_harness.agent.sub_agents.supervision_hub.*

[OUTPUT]
- Pytest test cases verifying thread-safety, roster aggregation, steer, kill, and revive

[POS]
myrm-agent-harness/tests/agent/sub_agents/test_supervision_hub.py
"""

from __future__ import annotations

from myrm_agent_harness.agent.sub_agents.supervision_hub import (
    SubagentRosterOverview,
    SubagentSupervisionCoordinator,
    SubagentTranscriptBuffer,
)


def test_transcript_buffer_ring_capacity_and_snapshot() -> None:
    buf = SubagentTranscriptBuffer(task_id="task-test-01", max_entries=3)
    assert len(buf) == 0

    buf.append_entry("bash", "echo 1", "1", "info")
    buf.append_entry("read_file", "path=a.py", "content", "info")
    buf.append_entry("write_file", "path=b.py", "ok", "info")
    assert len(buf) == 3

    # Add 4th entry, oldest should be evicted
    buf.append_entry("python", "run()", "done", "warn")
    assert len(buf) == 3

    entries = buf.get_entries()
    assert len(entries) == 3
    assert entries[0].tool_name == "read_file"
    assert entries[2].tool_name == "python"
    assert entries[2].level == "warn"


def test_supervision_coordinator_register_and_roster_overview() -> None:
    coord = SubagentSupervisionCoordinator()
    session_id = "chat-sess-991"

    w1 = coord.register_worker(session_id, "worker-1", "researcher", "Search web", model="gpt-4o")
    w2 = coord.register_worker(session_id, "worker-2", "coder", "Write python code", model="claude-3-5-sonnet")

    assert w1.status == "running"
    assert w2.status == "running"

    coord.update_worker_activity(
        "worker-1",
        current_activity="Searching duckduckgo",
        last_tool="web_search",
        tokens_delta=1500,
        elapsed_seconds=12.5,
    )
    coord.update_worker_activity(
        "worker-2",
        current_activity="Writing tests",
        last_tool="write_file",
        tokens_delta=2800,
        elapsed_seconds=18.0,
        status="stuck",
    )

    overview: SubagentRosterOverview = coord.get_roster_overview(session_id)
    assert overview.total_workers == 2
    assert overview.active_workers == 1
    assert overview.stuck_workers == 1
    assert overview.total_tokens == 4300
    assert overview.total_duration_seconds == 18.0
    assert len(overview.workers) == 2


def test_supervision_coordinator_transcript_collection() -> None:
    coord = SubagentSupervisionCoordinator()
    coord.register_worker("chat-sess-1", "worker-tr-1", "explorer")

    coord.append_transcript("worker-tr-1", "bash", "ls -la", "total 0", "info", duration_ms=20)
    coord.append_transcript("worker-tr-1", "cat", "config.json", "{'key': 1}", "info", duration_ms=15)

    entries = coord.get_transcript_entries("worker-tr-1")
    assert len(entries) == 2
    assert entries[0]["tool_name"] == "bash"
    assert entries[1]["tool_name"] == "cat"
    assert entries[0]["duration_ms"] == 20


def test_supervision_actions_steer_kill_revive() -> None:
    coord = SubagentSupervisionCoordinator()
    session_id = "chat-sess-action"
    task_id = "worker-act-1"

    coord.register_worker(session_id, task_id, "planner")

    # 1. Steer action
    steer_fail = coord.execute_action(task_id, "steer", steering_message="   ")
    assert not steer_fail.success

    steer_ok = coord.execute_action(task_id, "steer", steering_message="Focus only on unit tests")
    assert steer_ok.success
    assert steer_ok.new_status == "running"

    # 2. Kill stuck worker
    kill_res = coord.execute_action(task_id, "kill")
    assert kill_res.success
    assert kill_res.new_status == "failed"

    # 3. Revive killed worker
    revive_res = coord.execute_action(task_id, "revive")
    assert revive_res.success
    assert revive_res.new_status == "running"

    # 4. Unknown worker
    unknown_res = coord.execute_action("worker-none", "kill")
    assert not unknown_res.success
