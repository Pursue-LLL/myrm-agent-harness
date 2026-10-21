"""[INPUT] types.py (DebateRoomState, DebateTurn, DebateSubtask, DebateParticipant, DebatePhase, DebateRole).
[OUTPUT] MultiAgentDebateManager: Lifecycle orchestrator for multi-agent workroom debate, task decomposition, and round convergence.
[POS] Core coordination engine governing group debate turns, anti-wheel-war thresholds, and leader consensus.
"""

from __future__ import annotations

import threading
import time
import uuid

from myrm_agent_harness.agent.sub_agents.debate.types import (
    DebateParticipant,
    DebatePhase,
    DebateRole,
    DebateRoomState,
    DebateSubtask,
    DebateSubtaskStatus,
    DebateTurn,
)


class MultiAgentDebateManager:
    """Thread-safe orchestrator managing multi-agent debate workrooms."""

    _DEFAULT_MAX_ROUNDS: int = 3

    def __init__(self) -> None:
        self._rooms: dict[str, DebateRoomState] = {}
        self._lock = threading.Lock()

    def create_room(
        self,
        room_id: str,
        chat_id: str,
        topic: str,
        leader_agent_id: str,
        participants: list[DebateParticipant],
        max_rounds: int = _DEFAULT_MAX_ROUNDS,
        kanban_board_id: str | None = None,
    ) -> DebateRoomState:
        """Initialize a new multi-agent debate workroom in decomposition phase."""
        with self._lock:
            # Ensure leader is present in participants
            leader_found = any(p.agent_id == leader_agent_id for p in participants)
            participant_list = list(participants)
            if not leader_found:
                participant_list.insert(
                    0,
                    DebateParticipant(
                        agent_id=leader_agent_id,
                        name="Team Leader",
                        role=DebateRole.LEADER,
                    ),
                )

            now = time.time()
            state = DebateRoomState(
                room_id=room_id,
                chat_id=chat_id,
                topic=topic,
                leader_agent_id=leader_agent_id,
                phase=DebatePhase.DECOMPOSITION,
                round_index=1,
                max_rounds=max(1, max_rounds),
                participants=participant_list,
                subtasks=[],
                turns=[],
                consensus_decision=None,
                kanban_board_id=kanban_board_id,
                created_at=now,
                updated_at=now,
            )
            self._rooms[room_id] = state
            return state

    def get_room(self, room_id: str) -> DebateRoomState | None:
        """Fetch current room state by room_id."""
        with self._lock:
            return self._rooms.get(room_id)

    def list_rooms(self, chat_id: str | None = None) -> list[DebateRoomState]:
        """List active rooms, optionally filtered by chat_id."""
        with self._lock:
            if chat_id is None:
                return list(self._rooms.values())
            return [r for r in self._rooms.values() if r.chat_id == chat_id]

    def decompose_task(
        self,
        room_id: str,
        subtasks: list[DebateSubtask],
    ) -> DebateRoomState:
        """Leader decomposes the root topic into assigned actionable subtasks."""
        with self._lock:
            room = self._rooms.get(room_id)
            if not room:
                raise KeyError(f"Debate room not found: {room_id}")

            room.subtasks = list(subtasks)
            room.phase = DebatePhase.ROUND_ARGUMENT
            room.updated_at = time.time()
            return room

    def post_argument(
        self,
        room_id: str,
        speaker_id: str,
        thesis: str,
        counter_points: list[str] | None = None,
        evidence: list[str] | None = None,
        confidence: float = 1.0,
        kanban_task_id: str | None = None,
    ) -> DebateTurn:
        """A specialist agent posts an argument, critique, or supporting evidence."""
        with self._lock:
            room = self._rooms.get(room_id)
            if not room:
                raise KeyError(f"Debate room not found: {room_id}")

            # Resolve participant profile
            participant = next((p for p in room.participants if p.agent_id == speaker_id), None)
            speaker_name = participant.name if participant else f"Agent-{speaker_id[:6]}"
            speaker_role = participant.role if participant else DebateRole.RESEARCHER

            # Defensive anti-wheel-war guard:
            # If current round reaches or exceeds max_rounds, force transition to CONVERGENCE
            if room.round_index >= room.max_rounds and room.phase != DebatePhase.CONVERGENCE:
                room.phase = DebatePhase.CONVERGENCE

            turn_id = f"turn-{uuid.uuid4().hex[:8]}"
            turn = DebateTurn(
                turn_id=turn_id,
                speaker_id=speaker_id,
                speaker_name=speaker_name,
                role=speaker_role,
                phase=room.phase,
                round_index=room.round_index,
                thesis=thesis,
                counter_points=list(counter_points or []),
                evidence=list(evidence or []),
                confidence=max(0.0, min(1.0, confidence)),
                kanban_task_id=kanban_task_id,
                created_at=time.time(),
            )

            room.turns.append(turn)
            room.updated_at = time.time()
            return turn

    def advance_phase(
        self,
        room_id: str,
        target_phase: DebatePhase | None = None,
    ) -> DebateRoomState:
        """Progress workroom phase sequentially or jump to a specified phase."""
        with self._lock:
            room = self._rooms.get(room_id)
            if not room:
                raise KeyError(f"Debate room not found: {room_id}")

            if target_phase is not None:
                room.phase = target_phase
            else:
                phase_order = [
                    DebatePhase.DECOMPOSITION,
                    DebatePhase.ROUND_ARGUMENT,
                    DebatePhase.CROSS_EXAMINATION,
                    DebatePhase.CONVERGENCE,
                    DebatePhase.SETTLED,
                ]
                try:
                    curr_idx = phase_order.index(room.phase)
                    if curr_idx < len(phase_order) - 1:
                        room.phase = phase_order[curr_idx + 1]
                except ValueError:
                    room.phase = DebatePhase.SETTLED

            if room.phase in (DebatePhase.ROUND_ARGUMENT, DebatePhase.CROSS_EXAMINATION):
                room.round_index += 1

            room.updated_at = time.time()
            return room

    def synthesize_and_converge(
        self,
        room_id: str,
        consensus_decision: str,
        settled_subtask_ids: list[str] | None = None,
    ) -> DebateRoomState:
        """Synthesizer or Leader concludes debate, records final consensus, and settles subtasks."""
        with self._lock:
            room = self._rooms.get(room_id)
            if not room:
                raise KeyError(f"Debate room not found: {room_id}")

            room.consensus_decision = consensus_decision
            room.phase = DebatePhase.SETTLED

            if settled_subtask_ids:
                settled_set = set(settled_subtask_ids)
                for subtask in room.subtasks:
                    if subtask.task_id in settled_set:
                        subtask.status = DebateSubtaskStatus.DONE

            room.updated_at = time.time()
            return room

    def update_subtask_status(
        self,
        room_id: str,
        task_id: str,
        status: DebateSubtaskStatus,
        kanban_task_id: str | None = None,
    ) -> DebateSubtask:
        """Update a single subtask's execution status and optional kanban reference."""
        with self._lock:
            room = self._rooms.get(room_id)
            if not room:
                raise KeyError(f"Debate room not found: {room_id}")

            target = next((s for s in room.subtasks if s.task_id == task_id), None)
            if not target:
                raise KeyError(f"Subtask not found in room {room_id}: {task_id}")

            target.status = status
            if kanban_task_id is not None:
                target.kanban_task_id = kanban_task_id

            room.updated_at = time.time()
            return target

    def cleanup_room(self, room_id: str) -> bool:
        """Delete a room from registry."""
        with self._lock:
            return self._rooms.pop(room_id, None) is not None

    def cleanup_chat(self, chat_id: str) -> int:
        """Evict all rooms belonging to a chat_id."""
        with self._lock:
            to_delete = [rid for rid, r in self._rooms.items() if r.chat_id == chat_id]
            for rid in to_delete:
                del self._rooms[rid]
            return len(to_delete)
