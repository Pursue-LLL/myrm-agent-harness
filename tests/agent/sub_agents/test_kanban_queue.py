"""Unit tests for Persistent Kanban Job Queue and Massive Parallel Dogfooding Runner."""

import json
import pytest
from myrm_agent_harness.agent.sub_agents.kanban_queue import (
    BatchRunnerConfig,
    JobPriority,
    KanbanJobStatus,
    MassiveParallelBatchRunner,
    PersistentKanbanQueueManager,
    SwarmTopologyStage,
)


def test_kanban_create_and_show() -> None:
    mgr = PersistentKanbanQueueManager()
    job = mgr.kanban_create(
        title="Implement Queue Manager",
        goal="Build robust 5-state lifecycle",
        approach="Use dataclass and acyclic graph",
        acceptance_criteria=["Tests pass", "Ruff clean"],
        priority=JobPriority.HIGH,
        stage=SwarmTopologyStage.PARALLEL_SPECIALIST,
        assignee="worker-1",
    )

    assert job.job_id.startswith("job-")
    assert job.status == KanbanJobStatus.READY
    assert job.priority == JobPriority.HIGH
    assert job.worktree_path == f".worktrees/job-{job.job_id}"

    retrieved = mgr.kanban_show(job.job_id)
    assert retrieved is not None
    assert retrieved.title == "Implement Queue Manager"

    listed = mgr.kanban_list(status=KanbanJobStatus.READY)
    assert len(listed) == 1
    assert listed[0].job_id == job.job_id


def test_kanban_claim_and_complete_unblocking() -> None:
    mgr = PersistentKanbanQueueManager()
    job_a = mgr.kanban_create(title="Task A", goal="Do A")
    job_b = mgr.kanban_create(title="Task B", goal="Do B", dependencies=[job_a.job_id])

    assert job_a.status == KanbanJobStatus.READY
    assert job_b.status == KanbanJobStatus.TODO  # Waiting on Task A

    # Claim and run Task A
    claimed_a = mgr.kanban_claim_or_run(job_a.job_id, assignee="specialist-a")
    assert claimed_a.status == KanbanJobStatus.RUNNING
    assert claimed_a.assignee == "specialist-a"

    # Complete Task A -> should automatically unblock Task B to READY
    completed_a = mgr.kanban_complete(job_a.job_id, summary="Task A finished", metadata={"diff": "+10 -2"})
    assert completed_a.status == KanbanJobStatus.DONE
    assert completed_a.result_summary == "Task A finished"

    retrieved_b = mgr.kanban_show(job_b.job_id)
    assert retrieved_b is not None
    assert retrieved_b.status == KanbanJobStatus.READY


def test_kanban_block_and_unblock() -> None:
    mgr = PersistentKanbanQueueManager()
    job = mgr.kanban_create(title="Test Job", goal="Verify blocking")

    blocked = mgr.kanban_block(job.job_id, reason="Missing database credentials")
    assert blocked.status == KanbanJobStatus.BLOCKED
    assert blocked.blocked_reason == "Missing database credentials"

    unblocked = mgr.kanban_unblock(job.job_id)
    assert unblocked.status == KanbanJobStatus.READY
    assert unblocked.blocked_reason is None


def test_kanban_heartbeat_and_stale_reclamation() -> None:
    mgr = PersistentKanbanQueueManager(stale_timeout_seconds=14400.0)
    job = mgr.kanban_create(title="Long Task", goal="Long running work")
    mgr.kanban_claim_or_run(job.job_id, assignee="worker-slow")

    # Record normal heartbeat
    assert mgr.kanban_heartbeat(job.job_id) is True

    # No reclamation when time has not elapsed
    reclaimed = mgr.reclaim_stale_workers(now=job.last_heartbeat_timestamp + 100.0)
    assert len(reclaimed) == 0

    # Simulate 5 hours elapsed (> 14400s)
    reclaimed_stale = mgr.reclaim_stale_workers(now=job.last_heartbeat_timestamp + 18000.0)
    assert job.job_id in reclaimed_stale

    reclaimed_job = mgr.kanban_show(job.job_id)
    assert reclaimed_job is not None
    assert reclaimed_job.status == KanbanJobStatus.READY
    assert reclaimed_job.failure_count == 1
    assert reclaimed_job.assignee is None

    # Simulate 2 more failures to trigger permanent BLOCKED
    reclaimed_job.status = KanbanJobStatus.RUNNING
    reclaimed_job.last_heartbeat_timestamp = 1000.0
    mgr.reclaim_stale_workers(now=20000.0)
    assert reclaimed_job.failure_count == 2

    reclaimed_job.status = KanbanJobStatus.RUNNING
    reclaimed_job.last_heartbeat_timestamp = 1000.0
    mgr.reclaim_stale_workers(now=20000.0)
    assert reclaimed_job.failure_count == 3
    assert reclaimed_job.status == KanbanJobStatus.BLOCKED


def test_kanban_comments_and_swarm_blackboard() -> None:
    mgr = PersistentKanbanQueueManager()
    job = mgr.kanban_create(
        title="Root Architecture",
        goal="Formulate swarm design",
        stage=SwarmTopologyStage.PLANNING_ROOT,
    )

    # Standard comment
    c1 = mgr.kanban_comment(job.job_id, author="human_lead", content="Please focus on security")
    assert c1.is_blackboard is False
    assert len(job.comments) == 1

    # Swarm blackboard JSON comment
    bb_json = json.dumps({"schema_version": "v2", "consensus": "approved", "shards": 4})
    c2 = mgr.kanban_comment(job.job_id, author="architect_bot", content=f"[swarm:blackboard] {bb_json}")
    assert c2.is_blackboard is True
    assert len(job.comments) == 2

    bb_entries = mgr.get_blackboard_entries(stage=SwarmTopologyStage.PLANNING_ROOT)
    assert len(bb_entries) == 1
    assert bb_entries[0].payload.get("consensus") == "approved"
    assert bb_entries[0].payload.get("shards") == "4"


def test_kanban_link_and_cycle_prevention() -> None:
    mgr = PersistentKanbanQueueManager()
    job_1 = mgr.kanban_create(title="Job 1", goal="Goal 1")
    job_2 = mgr.kanban_create(title="Job 2", goal="Goal 2")
    job_3 = mgr.kanban_create(title="Job 3", goal="Goal 3")

    # Link: Job 2 depends on Job 1
    assert mgr.kanban_link(from_job_id=job_1.job_id, to_job_id=job_2.job_id) is True
    # Link: Job 3 depends on Job 2
    assert mgr.kanban_link(from_job_id=job_2.job_id, to_job_id=job_3.job_id) is True

    # Link: Job 1 depends on Job 3 -> would create cycle (1 -> 2 -> 3 -> 1)
    assert mgr.kanban_link(from_job_id=job_3.job_id, to_job_id=job_1.job_id) is False
    # Self link is rejected
    assert mgr.kanban_link(from_job_id=job_1.job_id, to_job_id=job_1.job_id) is False


def test_kanban_specify_and_decompose_with_circuit_breaker() -> None:
    mgr = PersistentKanbanQueueManager()
    spec = mgr.kanban_specify("Build high-performance search proxy for open-perplexity")
    assert "open-perplexity" in str(spec["title"]) or "search" in str(spec["title"])
    assert len(spec["acceptance_criteria"]) >= 2

    parent = mgr.kanban_create(title=str(spec["title"]), goal=str(spec["goal"]))
    subtasks = [
        {"title": "Sub 1: Parser", "goal": "Parse inputs"},
        {"title": "Sub 2: Dispatcher", "goal": "Dispatch requests"},
    ]

    children = mgr.kanban_decompose(parent.job_id, subtasks)
    assert len(children) == 2
    assert children[0].dependencies == [parent.job_id]

    # Test circuit breaker
    mgr.set_auto_decompose_enabled(False)
    assert mgr.is_auto_decompose_enabled() is False

    with pytest.raises(RuntimeError, match="Hot circuit breaker active"):
        mgr.kanban_decompose(parent.job_id, subtasks)


def test_massive_parallel_batch_runner() -> None:
    mgr = PersistentKanbanQueueManager()
    for i in range(15):
        mgr.kanban_create(title=f"Parallel Task {i}", goal=f"Goal {i}")

    runner = MassiveParallelBatchRunner(mgr, config=BatchRunnerConfig(max_parallel=12))

    # Dispatch wave 1: should claim up to 12 jobs
    wave_1 = runner.dispatch_parallel_wave()
    assert wave_1["dispatched"] == 12
    assert wave_1["running"] == 12

    # Simulate completing 3 jobs
    active_jids = list(runner.active_workers.values())[:3]
    for jid in active_jids:
        t = runner.record_job_execution(
            job_id=jid,
            success=True,
            output_summary="Work finished flawlessly",
            tool_calls=[{"tool": "bash", "cmd": "pytest"}, {"tool": "file_write", "path": "test.py"}],
            turns_taken=3,
        )
        assert t.success is True
        assert t.tool_usage_stats.get("bash") == 1

    # Checkpoint status
    ckpt = runner.get_checkpoint_status()
    assert ckpt["done_jobs"] == 3
    assert ckpt["total_jobs"] == 15
    assert ckpt["trajectories_collected"] == 3

    # Export JSONL
    jsonl = runner.export_trajectories_jsonl()
    lines = jsonl.strip().split("\n")
    assert len(lines) == 3
    first_record = json.loads(lines[0])
    assert first_record["final_response"] == "Work finished flawlessly"
    assert "tool_usage_stats" in first_record
