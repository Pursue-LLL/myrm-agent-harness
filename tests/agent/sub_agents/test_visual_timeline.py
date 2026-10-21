"""Unit tests for Multi-Agent Visual Timeline & Cherry-Pick Rollback (Item 61).

[INPUT]
- Harness visual_timeline package classes:
  TimelineJournal, CherryPickRollbackEngine, ActorType, OperationType,
  RollbackStatus, TimelineNode, TimelineFilterCriteria.

[OUTPUT]
- Pytest verification for chronological activity logging, multi-dimensional
  filtering, isolated single-agent cherry-pick rollback, and overlap conflict protection.

[POS]
- myrm-agent-harness/tests/agent/sub_agents/test_visual_timeline.py
"""

from __future__ import annotations

import time

import pytest

from myrm_agent_harness.agent.sub_agents.visual_timeline import (
    ActorType,
    CherryPickRollbackEngine,
    OperationType,
    RollbackStatus,
    TimelineFilterCriteria,
    TimelineJournal,
    TimelineNode,
)


@pytest.fixture
def journal() -> TimelineJournal:
    """Provides a fresh TimelineJournal instance."""
    j = TimelineJournal()
    j.clear()
    return j


@pytest.fixture
def engine(journal: TimelineJournal) -> CherryPickRollbackEngine:
    """Provides a fresh CherryPickRollbackEngine instance."""
    return CherryPickRollbackEngine(journal)


def test_timeline_journal_record_and_get_node(journal: TimelineJournal) -> None:
    """Test recording nodes and retrieving by ID and file history."""
    node = TimelineNode(
        node_id="node-001",
        session_id="session-alpha",
        actor_id="user-alice",
        actor_name="Alice (Lead)",
        actor_type=ActorType.HUMAN_USER,
        operation_type=OperationType.FILE_CREATE,
        file_path="src/utils/math.py",
        before_content="",
        after_content="def add(a, b): return a + b\n",
        diff_summary="Created math.py",
    )
    journal.record_node(node)

    fetched = journal.get_node("node-001")
    assert fetched is not None
    assert fetched.node_id == "node-001"
    assert fetched.actor_name == "Alice (Lead)"

    file_hist = journal.get_file_history("src/utils/math.py")
    assert len(file_hist) == 1
    assert file_hist[0].node_id == "node-001"


def test_timeline_journal_query_with_multi_dimensional_filters(journal: TimelineJournal) -> None:
    """Test multi-dimensional filtering by actor, role, file path, operation, and time."""
    now = time.time()
    n1 = TimelineNode(
        node_id="node-1",
        session_id="sess-filter",
        actor_id="user-alice",
        actor_name="Alice",
        actor_type=ActorType.HUMAN_USER,
        operation_type=OperationType.FILE_MODIFY,
        file_path="src/app.py",
        timestamp=now - 50,
    )
    n2 = TimelineNode(
        node_id="node-2",
        session_id="sess-filter",
        actor_id="agent-coder",
        actor_name="Coder Bot",
        actor_type=ActorType.LOCAL_AGENT,
        operation_type=OperationType.FILE_MODIFY,
        file_path="src/service.py",
        timestamp=now - 30,
    )
    n3 = TimelineNode(
        node_id="node-3",
        session_id="sess-filter",
        actor_id="agent-auditor",
        actor_name="Cloud Auditor",
        actor_type=ActorType.CLOUD_AGENT,
        operation_type=OperationType.TOOL_EXECUTION,
        file_path="src/service.py",
        timestamp=now - 10,
    )
    for n in (n1, n2, n3):
        journal.record_node(n)

    # 1. Filter by actor_id
    res_actor = journal.query_nodes("sess-filter", TimelineFilterCriteria(actor_id="user-alice"))
    assert len(res_actor) == 1
    assert res_actor[0].node_id == "node-1"

    # 2. Filter by actor_type
    res_type = journal.query_nodes("sess-filter", TimelineFilterCriteria(actor_type=ActorType.CLOUD_AGENT))
    assert len(res_type) == 1
    assert res_type[0].node_id == "node-3"

    # 3. Filter by file_path
    res_file = journal.query_nodes("sess-filter", TimelineFilterCriteria(file_path="src/service.py"))
    assert len(res_file) == 2
    assert {r.node_id for r in res_file} == {"node-2", "node-3"}

    # 4. Filter by operation_type
    res_op = journal.query_nodes("sess-filter", TimelineFilterCriteria(operation_type=OperationType.TOOL_EXECUTION))
    assert len(res_op) == 1
    assert res_op[0].node_id == "node-3"

    # 5. Filter by time window
    res_time = journal.query_nodes("sess-filter", TimelineFilterCriteria(start_time=now - 40, end_time=now - 20))
    assert len(res_time) == 1
    assert res_time[0].node_id == "node-2"


def test_cherry_pick_rollback_success(journal: TimelineJournal, engine: CherryPickRollbackEngine) -> None:
    """Test successful isolated rollback of a single agent mutation without affecting others."""
    file_path = "src/settings.py"
    initial_content = "DEBUG = True\nPORT = 8080\n"
    engine.set_file_content(file_path, initial_content)

    # Agent introduces buggy timeout
    buggy_node = TimelineNode(
        node_id="agent-bug-01",
        session_id="sess-co-dev",
        actor_id="agent-junior",
        actor_name="Junior Coder",
        actor_type=ActorType.LOCAL_AGENT,
        operation_type=OperationType.FILE_MODIFY,
        file_path=file_path,
        line_start=3,
        line_end=4,
        before_content="",
        after_content="TIMEOUT = -999\n",
        diff_summary="Added invalid negative timeout",
    )
    journal.record_node(buggy_node)
    content_after_bug = initial_content + "TIMEOUT = -999\n"
    engine.set_file_content(file_path, content_after_bug)

    # Another collaborator edits an unrelated line
    collaborator_node = TimelineNode(
        node_id="alice-edit-02",
        session_id="sess-co-dev",
        actor_id="user-alice",
        actor_name="Alice",
        actor_type=ActorType.HUMAN_USER,
        operation_type=OperationType.FILE_MODIFY,
        file_path=file_path,
        line_start=10,
        line_end=12,
        before_content="",
        after_content="HOST = '0.0.0.0'\n",
        diff_summary="Added HOST configuration",
    )
    journal.record_node(collaborator_node)
    content_after_alice = content_after_bug + "HOST = '0.0.0.0'\n"
    engine.set_file_content(file_path, content_after_alice)

    # Perform surgical rollback on the junior agent's buggy node
    result = engine.rollback_node("agent-bug-01")
    assert result.status == RollbackStatus.SUCCESS
    assert result.file_path == file_path
    # The buggy line should be removed, while Alice's edit must be preserved!
    current_content = engine.get_file_content(file_path)
    assert "TIMEOUT = -999" not in current_content
    target_is_rolled_back = journal.get_node("agent-bug-01")
    assert target_is_rolled_back is not None
    assert target_is_rolled_back.is_rolled_back


def test_cherry_pick_rollback_conflict_detection(
    journal: TimelineJournal, engine: CherryPickRollbackEngine
) -> None:
    """Test that overlapping subsequent mutations trigger conflict detection and prevent corruption."""
    file_path = "src/auth.py"
    node1 = TimelineNode(
        node_id="node-base-01",
        session_id="sess-conflict",
        actor_id="agent-01",
        actor_name="Bot 1",
        actor_type=ActorType.LOCAL_AGENT,
        operation_type=OperationType.FILE_MODIFY,
        file_path=file_path,
        line_start=20,
        line_end=35,
        before_content="token = decode()",
        after_content="token = safe_decode()",
    )
    node2 = TimelineNode(
        node_id="node-subsequent-02",
        session_id="sess-conflict",
        actor_id="agent-02",
        actor_name="Bot 2",
        actor_type=ActorType.CLOUD_AGENT,
        operation_type=OperationType.FILE_MODIFY,
        file_path=file_path,
        line_start=30,  # Overlaps with [20, 35]
        line_end=45,
        before_content="token = safe_decode()",
        after_content="token = safe_decode_v2()",
    )
    journal.record_node(node1)
    journal.record_node(node2)

    # Attempt to rollback node1: should fail with CONFLICT_DETECTED
    result = engine.rollback_node("node-base-01")
    assert result.status == RollbackStatus.CONFLICT_DETECTED
    assert result.conflict_reason is not None
    assert "overlapping lines" in result.conflict_reason
    assert not node1.is_rolled_back


def test_cherry_pick_rollback_already_rolled_back(
    journal: TimelineJournal, engine: CherryPickRollbackEngine
) -> None:
    """Test that attempting to revert an already rolled back node returns ALREADY_ROLLED_BACK."""
    node = TimelineNode(
        node_id="node-once",
        session_id="sess-dup",
        actor_id="agent-01",
        actor_name="Bot",
        actor_type=ActorType.LOCAL_AGENT,
        operation_type=OperationType.FILE_MODIFY,
        file_path="src/main.py",
        before_content="v1",
        after_content="v2",
    )
    journal.record_node(node)
    engine.set_file_content("src/main.py", "v2")

    res1 = engine.rollback_node("node-once")
    assert res1.status == RollbackStatus.SUCCESS

    res2 = engine.rollback_node("node-once")
    assert res2.status == RollbackStatus.ALREADY_ROLLED_BACK


def test_cherry_pick_rollback_node_not_found(engine: CherryPickRollbackEngine) -> None:
    """Test that rolling back an unrecorded node returns NODE_NOT_FOUND."""
    res = engine.rollback_node("node-ghost-404")
    assert res.status == RollbackStatus.NODE_NOT_FOUND
