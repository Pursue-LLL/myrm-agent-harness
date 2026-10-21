from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.agent.sub_agents.lifecycle_toolchain import (
    SubagentLifecycleError,
    SubagentLifecycleManager,
    SubagentNotFoundError,
    SubagentSpawnRequest,
    SubagentStatusEnum,
)


def test_spawn_subagent_success() -> None:
    manager = SubagentLifecycleManager()
    req = SubagentSpawnRequest(
        task_prompt="Analyze code repository structure",
        parent_session_id="chat-root-001",
        agent_profile="repo_scout",
        tools_whitelist=["read_file", "list_dir"],
        timeout_seconds=60.0,
    )
    record = manager.spawn(req)
    assert record.subagent_id.startswith("subagent-")
    assert record.status == SubagentStatusEnum.RUNNING
    assert record.parent_session_id == "chat-root-001"
    assert len(record.events) == 1
    assert record.events[0].event_type == "SUBAGENT_SPAWNED"


def test_spawn_validation_errors() -> None:
    manager = SubagentLifecycleManager()
    with pytest.raises(SubagentLifecycleError, match="Task prompt cannot be empty"):
        manager.spawn(
            SubagentSpawnRequest(
                task_prompt="   ",
                parent_session_id="chat-root-001",
            )
        )

    with pytest.raises(SubagentLifecycleError, match="Parent session ID cannot be empty"):
        manager.spawn(
            SubagentSpawnRequest(
                task_prompt="Valid prompt",
                parent_session_id="   ",
            )
        )


def test_send_input_to_running_and_terminal() -> None:
    manager = SubagentLifecycleManager()
    record = manager.spawn(
        SubagentSpawnRequest(
            task_prompt="Scrape data",
            parent_session_id="chat-root-002",
        )
    )

    msg = manager.send_input(
        subagent_id=record.subagent_id,
        content="Focus on Python files only",
        sender_role="orchestrator",
    )
    assert msg.content == "Focus on Python files only"
    assert len(record.input_queue) == 1
    assert record.events[-1].event_type == "INPUT_INJECTED"

    # Complete it and ensure sending input fails
    manager.complete(record.subagent_id, result_summary="Done")
    with pytest.raises(SubagentLifecycleError, match="Cannot inject input to terminal subagent"):
        manager.send_input(record.subagent_id, "Additional input")


def test_kill_subagent() -> None:
    manager = SubagentLifecycleManager()
    record = manager.spawn(
        SubagentSpawnRequest(
            task_prompt="Long running task",
            parent_session_id="chat-root-003",
        )
    )

    killed = manager.kill(record.subagent_id, reason="Deadlock detected")
    assert killed.status == SubagentStatusEnum.KILLED
    assert killed.kill_reason == "Deadlock detected"
    assert killed.ended_at is not None
    assert killed.is_terminal() is True

    # Killing again is idempotent
    killed_again = manager.kill(record.subagent_id, reason="Another reason")
    assert killed_again.status == SubagentStatusEnum.KILLED


def test_complete_and_fail() -> None:
    manager = SubagentLifecycleManager()
    r1 = manager.spawn(
        SubagentSpawnRequest(task_prompt="Task 1", parent_session_id="chat-root-004")
    )
    r2 = manager.spawn(
        SubagentSpawnRequest(task_prompt="Task 2", parent_session_id="chat-root-004")
    )

    c1 = manager.complete(r1.subagent_id, result_summary="Success", token_usage=1200, step_count=5)
    assert c1.status == SubagentStatusEnum.COMPLETED
    assert c1.result_summary == "Success"
    assert c1.token_usage == 1200
    assert c1.step_count == 5

    f2 = manager.fail(r2.subagent_id, error_detail="Tool execution failed")
    assert f2.status == SubagentStatusEnum.FAILED
    assert f2.error_detail == "Tool execution failed"


def test_timeout_detection() -> None:
    manager = SubagentLifecycleManager()
    record = manager.spawn(
        SubagentSpawnRequest(
            task_prompt="Fast timeout task",
            parent_session_id="chat-root-005",
            timeout_seconds=5.0,
        )
    )
    # Manually backdate started_at to simulate expiration
    expired_time = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    record.started_at = expired_time

    timed_out = manager.check_timeouts()
    assert record.subagent_id in timed_out

    refreshed = manager.get_subagent(record.subagent_id)
    assert refreshed.status == SubagentStatusEnum.TIMEOUT
    assert "Execution timed out" in (refreshed.error_detail or "")


def test_wait_and_list_subagents() -> None:
    manager = SubagentLifecycleManager()
    r1 = manager.spawn(
        SubagentSpawnRequest(task_prompt="Task A", parent_session_id="sess-A")
    )
    r2 = manager.spawn(
        SubagentSpawnRequest(task_prompt="Task B", parent_session_id="sess-A")
    )
    r3 = manager.spawn(
        SubagentSpawnRequest(task_prompt="Task C", parent_session_id="sess-B")
    )

    manager.complete(r1.subagent_id, result_summary="A done")
    manager.fail(r2.subagent_id, error_detail="B failed")

    wait_res = manager.wait([r1.subagent_id, r2.subagent_id], timeout_seconds=1.0)
    assert wait_res.all_completed is True
    assert wait_res.completed_count == 1
    assert wait_res.failed_count == 1
    assert len(wait_res.tasks) == 2

    # Listing by session
    sess_a_list = manager.list_subagents(parent_session_id="sess-A")
    assert len(sess_a_list) == 2

    running_list = manager.list_subagents(status_filter=SubagentStatusEnum.RUNNING)
    assert len(running_list) == 1
    assert running_list[0].subagent_id == r3.subagent_id

    # Non-existent subagent lookup
    with pytest.raises(SubagentNotFoundError):
        manager.get_subagent("non-existent-id")
