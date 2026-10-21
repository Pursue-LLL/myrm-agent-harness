"""[INPUT] None.
[OUTPUT] Unit test suite for Multi-Agent Debate Workroom & Kanban Integration.
[POS] Subagent debate engine testing.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.sub_agents.debate import (
    DebateKanbanBridge,
    DebateParticipant,
    DebatePhase,
    DebateRole,
    DebateSubtask,
    DebateSubtaskStatus,
    MultiAgentDebateManager,
)


@pytest.fixture
def debate_mgr() -> MultiAgentDebateManager:
    return MultiAgentDebateManager()


def test_room_initialization_with_leader_and_participants(
    debate_mgr: MultiAgentDebateManager,
) -> None:
    participants = [
        DebateParticipant(agent_id="agt-critic", name="Critic Bot", role=DebateRole.CRITIC),
        DebateParticipant(agent_id="agt-coder", name="Coder Bot", role=DebateRole.IMPLEMENTER),
    ]

    state = debate_mgr.create_room(
        room_id="room-test-1",
        chat_id="chat-100",
        topic="Optimize high-concurrency websocket pipeline",
        leader_agent_id="agt-leader",
        participants=participants,
        max_rounds=3,
        kanban_board_id="board-alpha",
    )

    assert state.room_id == "room-test-1"
    assert state.phase == DebatePhase.DECOMPOSITION
    assert state.round_index == 1
    assert state.max_rounds == 3
    assert state.kanban_board_id == "board-alpha"
    # Leader automatically added to participant list
    assert any(p.agent_id == "agt-leader" and p.role == DebateRole.LEADER for p in state.participants)
    assert len(state.participants) == 3


def test_task_decomposition_and_phase_progression(
    debate_mgr: MultiAgentDebateManager,
) -> None:
    debate_mgr.create_room(
        room_id="room-decomp",
        chat_id="chat-101",
        topic="Design cross-chain liquidity router",
        leader_agent_id="agt-lead",
        participants=[],
    )

    subtasks = [
        DebateSubtask(
            task_id="st-1",
            title="Protocol security audit",
            description="Examine bridge replay attack vectors",
            assigned_agent_id="agt-critic",
            assigned_role=DebateRole.CRITIC,
        ),
        DebateSubtask(
            task_id="st-2",
            title="State machine implementation",
            description="Write idempotent balance ledger",
            assigned_agent_id="agt-coder",
            assigned_role=DebateRole.IMPLEMENTER,
        ),
    ]

    state = debate_mgr.decompose_task("room-decomp", subtasks)
    assert state.phase == DebatePhase.ROUND_ARGUMENT
    assert len(state.subtasks) == 2
    assert state.subtasks[0].status == DebateSubtaskStatus.TODO


def test_argument_posting_and_anti_wheel_war_guard(
    debate_mgr: MultiAgentDebateManager,
) -> None:
    participants = [
        DebateParticipant(agent_id="agt-lead", name="Lead", role=DebateRole.LEADER),
        DebateParticipant(agent_id="agt-critic", name="Critic", role=DebateRole.CRITIC),
    ]
    # Set max_rounds to 1 so the second round triggers the guard
    debate_mgr.create_room(
        room_id="room-guard",
        chat_id="chat-102",
        topic="Evaluate SQLite vs RocksDB for high-write telemetry",
        leader_agent_id="agt-lead",
        participants=participants,
        max_rounds=1,
    )
    debate_mgr.decompose_task("room-guard", [])

    # Post turn 1 under round 1
    turn1 = debate_mgr.post_argument(
        room_id="room-guard",
        speaker_id="agt-critic",
        thesis="RocksDB has superior write throughput under LSM tree",
        counter_points=["SQLite write lock will bottleneck concurrent threads"],
        evidence=["Benchmark shows 45k ops/sec vs 12k ops/sec"],
        confidence=0.92,
    )
    assert turn1.speaker_name == "Critic"
    assert turn1.confidence == 0.92
    assert len(turn1.counter_points) == 1

    # Now room round_index is 1, which equals max_rounds (1)
    # Next argument post triggers anti-wheel-war guard -> forcing phase to CONVERGENCE
    turn2 = debate_mgr.post_argument(
        room_id="room-guard",
        speaker_id="agt-lead",
        thesis="Acknowledge LSM benefits, but RocksDB adds CGO and binary size overhead",
    )
    assert turn2.phase == DebatePhase.CONVERGENCE
    refreshed_room = debate_mgr.get_room("room-guard")
    assert refreshed_room is not None
    assert refreshed_room.phase == DebatePhase.CONVERGENCE


def test_synthesize_consensus_and_settle_subtasks(
    debate_mgr: MultiAgentDebateManager,
) -> None:
    debate_mgr.create_room(
        room_id="room-synth",
        chat_id="chat-103",
        topic="API Protocol Selection: REST vs gRPC",
        leader_agent_id="agt-lead",
        participants=[],
    )
    subtasks = [
        DebateSubtask(
            task_id="st-api-1",
            title="Benchmark HTTP/2 framing overhead",
            description="Measure serialization latency",
            assigned_agent_id="agt-lead",
            assigned_role=DebateRole.LEADER,
        ),
        DebateSubtask(
            task_id="st-api-2",
            title="Browser client compatibility matrix",
            description="Evaluate gRPC-Web proxy complexity",
            assigned_agent_id="agt-lead",
            assigned_role=DebateRole.LEADER,
        ),
    ]
    debate_mgr.decompose_task("room-synth", subtasks)

    state = debate_mgr.synthesize_and_converge(
        room_id="room-synth",
        consensus_decision="Adopt REST/JSON for web client and gRPC for internal microservices.",
        settled_subtask_ids=["st-api-1"],
    )

    assert state.phase == DebatePhase.SETTLED
    assert "Adopt REST/JSON" in (state.consensus_decision or "")
    assert state.subtasks[0].status == DebateSubtaskStatus.DONE
    assert state.subtasks[1].status == DebateSubtaskStatus.TODO


def test_kanban_bridge_mapping_and_payload_generation() -> None:
    # Test bidirectional status mappings
    assert DebateKanbanBridge.to_kanban_status(DebateSubtaskStatus.TODO) == "READY"
    assert DebateKanbanBridge.to_kanban_status(DebateSubtaskStatus.IN_PROGRESS) == "RUNNING"
    assert DebateKanbanBridge.to_kanban_status(DebateSubtaskStatus.BLOCKED) == "BLOCKED"
    assert DebateKanbanBridge.to_kanban_status(DebateSubtaskStatus.IN_REVIEW) == "IN_REVIEW"
    assert DebateKanbanBridge.to_kanban_status(DebateSubtaskStatus.DONE) == "COMPLETED"

    assert DebateKanbanBridge.to_debate_status("READY") == DebateSubtaskStatus.TODO
    assert DebateKanbanBridge.to_debate_status("RUNNING") == DebateSubtaskStatus.IN_PROGRESS
    assert DebateKanbanBridge.to_debate_status("COMPLETED") == DebateSubtaskStatus.DONE

    subtask = DebateSubtask(
        task_id="sub-42",
        title="Refactor auth middleware",
        description="Replace HMAC with Ed25519 signatures",
        assigned_agent_id="agent-sec",
        assigned_role=DebateRole.CRITIC,
        status=DebateSubtaskStatus.IN_PROGRESS,
    )

    payload = DebateKanbanBridge.build_kanban_task_payload("room-sec-99", subtask)
    assert payload["title"] == "[CRITIC] Refactor auth middleware"
    assert payload["initial_status"] == "RUNNING"
    assert "debate-workroom" in payload["tags"]
    assert "room:room-sec-99" in payload["tags"]

    # Test sync subtask with kanban
    synced = DebateKanbanBridge.sync_subtask_with_kanban(subtask, "kanban-card-100", "COMPLETED")
    assert synced.kanban_task_id == "kanban-card-100"
    assert synced.status == DebateSubtaskStatus.DONE


def test_room_and_chat_cleanup(debate_mgr: MultiAgentDebateManager) -> None:
    debate_mgr.create_room(
        room_id="room-del-1",
        chat_id="chat-clean",
        topic="T1",
        leader_agent_id="l1",
        participants=[],
    )
    debate_mgr.create_room(
        room_id="room-del-2",
        chat_id="chat-clean",
        topic="T2",
        leader_agent_id="l1",
        participants=[],
    )
    debate_mgr.create_room(
        room_id="room-del-3",
        chat_id="chat-other",
        topic="T3",
        leader_agent_id="l1",
        participants=[],
    )

    assert len(debate_mgr.list_rooms("chat-clean")) == 2

    # Single room cleanup
    assert debate_mgr.cleanup_room("room-del-1") is True
    assert debate_mgr.cleanup_room("non-existent") is False
    assert len(debate_mgr.list_rooms("chat-clean")) == 1

    # Chat scoped bulk cleanup
    deleted_count = debate_mgr.cleanup_chat("chat-clean")
    assert deleted_count == 1
    assert len(debate_mgr.list_rooms("chat-clean")) == 0
    assert len(debate_mgr.list_rooms("chat-other")) == 1
