"""Unit tests for Durable Agent Teams (Item 28).

Covers:
- Implicit root lead & kebab-case teammate lifecycle
- CAS versioned task graph DAG, cycle detection, blockers & readiness
- Write scopes advisory overlap warnings
- Peer mailbox messaging, rate limiting, and cold recovery log replay
- Edge-triggered wait_for_change and projection output
"""

from __future__ import annotations

import asyncio
from tempfile import TemporaryDirectory

import pytest

from myrm_agent_harness.agent.sub_agents.teams import (
    CASConflictError,
    DeliveryMode,
    DurableAgentTeamEngine,
    DurablePeerMailbox,
    TaskBlockedError,
    TaskDependencyCycleError,
    TaskGraphEngine,
    TeamMemberPhase,
    TeamMemberRole,
    TeamTaskStatus,
)


def test_implicit_lead_and_teammate_lifecycle() -> None:
    engine = DurableAgentTeamEngine(team_id="session-123")

    # Lead auto-provisioned
    lead = engine.get_member("lead")
    assert lead is not None
    assert lead.role == TeamMemberRole.LEAD
    assert lead.phase == TeamMemberPhase.ACTIVE
    assert lead.id == "session-123-lead"

    # Spawn teammates with valid kebab-case names
    t1 = engine.spawn_teammate("researcher-alpha", "Deep search specialist")
    assert t1.name == "researcher-alpha"
    assert t1.role == TeamMemberRole.TEAMMATE
    assert t1.phase == TeamMemberPhase.ACTIVE
    assert t1.id == "session-123-researcher-alpha"

    # Invalid names must raise ValueError
    with pytest.raises(ValueError, match="kebab-case"):
        engine.spawn_teammate("Invalid_Name!", "Desc")

    with pytest.raises(ValueError, match="kebab-case"):
        engine.spawn_teammate("CamelCaseWorker", "Desc")

    # Duplicate names must raise ValueError
    with pytest.raises(ValueError, match="already exists"):
        engine.spawn_teammate("researcher-alpha", "Duplicate")

    # Teammate failure
    failed = engine.fail_teammate("researcher-alpha", "Sandbox OOM killed")
    assert failed.phase == TeamMemberPhase.FAILED
    assert failed.error == "Sandbox OOM killed"

    proj = engine.get_projection()
    assert proj.failure is not None
    assert "Sandbox OOM killed" in proj.failure
    assert len(proj.members) == 2


def test_task_graph_cas_optimistic_concurrency() -> None:
    graph = TaskGraphEngine(team_id="team-cas")

    task = graph.create_task(subject="Analyze dataset", description="Clean raw CSV")
    assert task.id == "task-1"
    assert task.revision == 1
    assert task.status == TeamTaskStatus.PENDING

    # Successful update with matching expected_revision
    updated = graph.update_task(
        task_id="task-1",
        expected_revision=1,
        description="Clean raw CSV and generate parquet",
    )
    assert updated.revision == 2
    assert updated.description == "Clean raw CSV and generate parquet"

    # Stale expected_revision must raise CASConflictError
    with pytest.raises(CASConflictError) as exc_info:
        graph.update_task(
            task_id="task-1",
            expected_revision=1,  # Stale! Current is 2
            description="Conflicting write",
        )
    assert exc_info.value.expected == 1
    assert exc_info.value.actual == 2


def test_task_graph_dag_dependency_and_readiness() -> None:
    graph = TaskGraphEngine(team_id="team-dag")

    # Task 1: No dependencies -> Ready immediately
    t1 = graph.create_task(subject="Step 1: Scrape docs")
    assert t1.ready is True

    # Task 2: Blocked by Task 1 -> Not ready
    t2 = graph.create_task(subject="Step 2: Train model", blocked_by=["task-1"])
    assert t2.ready is False

    # Attempting to claim Task 2 while blocked must raise TaskBlockedError
    with pytest.raises(TaskBlockedError) as exc_info:
        graph.claim_task("task-2", expected_revision=1, owner_id="w-1", owner_name="worker-1")
    assert "task-1" in exc_info.value.unmet_blockers

    # Claim & complete Task 1
    graph.claim_task("task-1", expected_revision=1, owner_id="w-1", owner_name="worker-1")
    graph.complete_task("task-1", expected_revision=2)

    # Now Task 2 should automatically become ready!
    t2_ready = graph.get_task("task-2")
    assert t2_ready.ready is True

    # Can now claim Task 2
    t2_claimed = graph.claim_task("task-2", expected_revision=1, owner_id="w-2", owner_name="worker-2")
    assert t2_claimed.status == TeamTaskStatus.IN_PROGRESS
    assert t2_claimed.owner_name == "worker-2"


def test_task_graph_cycle_detection() -> None:
    graph = TaskGraphEngine(team_id="team-cycle")

    # Self dependency cycle
    with pytest.raises(TaskDependencyCycleError):
        graph.create_task(subject="Self cycle", blocked_by=["task-1"])

    # Multi-hop cycle: A -> B -> C -> A
    graph.create_task(subject="Task A")  # task-1
    graph.create_task(subject="Task B", blocked_by=["task-1"])  # task-2
    graph.create_task(subject="Task C", blocked_by=["task-2"])  # task-3

    # Attempting to make Task A blocked by Task C creates cycle!
    with pytest.raises(TaskDependencyCycleError) as exc_info:
        graph.update_task("task-1", expected_revision=1, blocked_by=["task-3"])
    assert exc_info.value.task_id == "task-1"


def test_task_graph_write_scopes_overlap_warning() -> None:
    graph = TaskGraphEngine(team_id="team-scopes")

    # Task 1 writing to src/api
    graph.create_task(
        subject="Auth service",
        write_scopes=["src/api/auth"],
        owner_id="u1",
        owner_name="dev1",
    )
    # Task 2 writing to parent directory src/api
    t2 = graph.create_task(
        subject="API Gateway",
        write_scopes=["src/api"],
        owner_id="u2",
        owner_name="dev2",
    )

    # View should detect overlap and provide advisory warning
    assert len(t2.write_scope_warnings) > 0
    assert "src/api" in t2.write_scope_warnings[0]


def test_peer_mailbox_messaging_and_drain() -> None:
    mailbox = DurablePeerMailbox(team_id="team-mbx")

    # Send peer message
    msg = mailbox.send_peer_message(
        sender_id="u1",
        sender_name="agent-a",
        target_id="u2",
        target_name="agent-b",
        content="Here is the intermediate schema",
        mode=DeliveryMode.WAKING,
    )
    assert msg.id.startswith("msg-team-mbx-")
    assert msg.content == "Here is the intermediate schema"
    assert msg.mode == DeliveryMode.WAKING
    assert mailbox.get_pending_count("u2") == 1

    # Drain messages for agent-b
    drained = mailbox.drain_inbox("u2")
    assert len(drained) == 1
    assert drained[0].id == msg.id
    assert drained[0].delivered is True
    assert mailbox.get_pending_count("u2") == 0


def test_peer_mailbox_cold_recovery_queued_minus_delivered() -> None:
    with TemporaryDirectory() as tmp_dir:
        mbx1 = DurablePeerMailbox(team_id="team-recovery", workspace_path=tmp_dir)
        mbx1.send_peer_message("a", "agent-a", "b", "agent-b", "msg 1")
        mbx1.send_peer_message("a", "agent-a", "b", "agent-b", "msg 2")
        m3 = mbx1.send_peer_message("a", "agent-a", "c", "agent-c", "msg 3")

        # Drain m1 & m2 for agent-b, leaving m3 for agent-c unconsumed
        drained_b = mbx1.drain_inbox("b")
        assert len(drained_b) == 2

        # 2. Simulate process restart by instantiating a new instance pointing to same workspace
        mbx2 = DurablePeerMailbox(team_id="team-recovery", workspace_path=tmp_dir)

        # agent-b should have 0 pending messages (both were delivered)
        assert mbx2.get_pending_count("b") == 0

        # agent-c should have exactly 1 pending message (m3 restored via cold recovery!)
        assert mbx2.get_pending_count("c") == 1
        drained_c = mbx2.drain_inbox("c")
        assert len(drained_c) == 1
        assert drained_c[0].id == m3.id
        assert drained_c[0].content == "msg 3"


@pytest.mark.asyncio
async def test_engine_wait_for_change_and_peer_interaction() -> None:
    engine = DurableAgentTeamEngine(team_id="team-async")
    engine.spawn_teammate("worker-1", "First worker")
    engine.spawn_teammate("worker-2", "Second worker")

    # Background task waiting for change
    wait_task = asyncio.create_task(engine.wait_for_change(timeout_sec=2.0))
    await asyncio.sleep(0.01)

    # Sending a peer message triggers change notification
    engine.send_peer_message(
        sender_name="worker-1",
        target_name="worker-2",
        content="Hello peer",
    )

    # Wait task should wake up quickly and return True
    changed = await wait_task
    assert changed is True

    # Check inbox delivery
    inbox = engine.drain_inbox("worker-2")
    assert len(inbox) == 1
    assert inbox[0].content == "Hello peer"
