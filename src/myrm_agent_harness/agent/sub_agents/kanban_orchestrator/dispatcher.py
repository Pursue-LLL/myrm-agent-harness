"""Kanban Card Lifecycle Dispatcher with Card-Scoped Sandboxes and Auto-Unblock Cascades."""

from __future__ import annotations

import time
import uuid

from myrm_agent_harness.agent.sub_agents.kanban_orchestrator.dag_engine import (
    KanbanTaskDagEngine,
)
from myrm_agent_harness.agent.sub_agents.kanban_orchestrator.types import (
    CardArtifactDTO,
    CardPriorityEnum,
    KanbanBlockedCardError,
    KanbanBoardStateDTO,
    KanbanCardDTO,
    KanbanCardNotFoundError,
    KanbanLaneEnum,
)


class KanbanCardLifecycleDispatcher:
    """Manages the full lifecycle of multi-agent Kanban cards with DAG-driven auto-unblocking."""

    def __init__(self) -> None:
        self._boards: dict[str, KanbanBoardStateDTO] = {}

    def create_board(self, board_id: str, session_id: str, title: str) -> KanbanBoardStateDTO:
        """Initialize or retrieve a persistent project board."""
        now = time.time()
        board = KanbanBoardStateDTO(
            board_id=board_id,
            session_id=session_id,
            title=title,
            cards={},
            created_at=now,
            updated_at=now,
        )
        self._boards[board_id] = board
        return board

    def get_board(self, board_id: str) -> KanbanBoardStateDTO:
        """Retrieve board state by ID."""
        if board_id not in self._boards:
            raise KanbanCardNotFoundError(f"Board '{board_id}' not found.")
        return self._boards[board_id]

    def list_boards(self) -> list[KanbanBoardStateDTO]:
        """List all active Kanban boards."""
        return list(self._boards.values())

    def create_card(
        self,
        board_id: str,
        title: str,
        description: str,
        assigned_agent: str,
        depends_on: list[str] | None = None,
        priority: CardPriorityEnum = CardPriorityEnum.MEDIUM,
        initial_lane: KanbanLaneEnum | None = None,
    ) -> KanbanCardDTO:
        """Create a new task card with dependency validation and card-scoped sandbox assignment."""
        board = self.get_board(board_id)
        card_id = f"card-{uuid.uuid4().hex[:8]}"
        deps = list(depends_on or [])

        # Validate proposed dependencies against existing cards
        simulated_cards = dict(board.cards)
        dummy_card = KanbanCardDTO(
            card_id=card_id,
            board_id=board_id,
            title=title,
            description=description,
            lane=KanbanLaneEnum.TODO,
            priority=priority,
            assigned_agent=assigned_agent,
            depends_on=deps,
            blocked_by=[],
            sandbox_subdir=f"tasks/{card_id}",
            created_at=time.time(),
            updated_at=time.time(),
        )
        simulated_cards[card_id] = dummy_card
        KanbanTaskDagEngine.validate_dependencies(simulated_cards)

        # Compute blocked status
        unresolved = KanbanTaskDagEngine.compute_blocked_status(dummy_card, board.cards)
        effective_lane = initial_lane or KanbanLaneEnum.TODO
        if unresolved:
            effective_lane = KanbanLaneEnum.BLOCKED

        now = time.time()
        card = KanbanCardDTO(
            card_id=card_id,
            board_id=board_id,
            title=title,
            description=description,
            lane=effective_lane,
            priority=priority,
            assigned_agent=assigned_agent,
            depends_on=deps,
            blocked_by=unresolved,
            sandbox_subdir=f"tasks/{card_id}",
            artifacts=[],
            created_at=now,
            updated_at=now,
        )

        board.cards[card_id] = card
        board.updated_at = now
        return card

    def transition_card(
        self,
        board_id: str,
        card_id: str,
        target_lane: KanbanLaneEnum,
        actor: str = "system",
    ) -> tuple[KanbanCardDTO, list[str]]:
        """Transition a card to a target lane and trigger auto-unblock cascade for downstream cards."""
        board = self.get_board(board_id)
        if card_id not in board.cards:
            raise KanbanCardNotFoundError(f"Card '{card_id}' not found in board '{board_id}'.")

        card = board.cards[card_id]
        if card.lane == target_lane:
            return card, []

        now = time.time()

        # Prevent moving to IN_PROGRESS or DONE while dependencies remain unresolved
        if target_lane in (KanbanLaneEnum.IN_PROGRESS, KanbanLaneEnum.DONE):
            unresolved = KanbanTaskDagEngine.compute_blocked_status(card, board.cards)
            if unresolved:
                raise KanbanBlockedCardError(
                    f"Card '{card_id}' cannot transition to '{target_lane}' because prerequisites {unresolved} are not completed."
                )

        unlocked_downstreams: list[str] = []

        if target_lane == KanbanLaneEnum.DONE:
            card.completed_at = now
            # Find and auto-unblock downstream cards
            unblockable = KanbanTaskDagEngine.find_auto_unblockable_downstreams(card_id, board.cards)
            for d_id in unblockable:
                downstream = board.cards[d_id]
                downstream.lane = KanbanLaneEnum.TODO
                downstream.blocked_by = []
                downstream.updated_at = now
                unlocked_downstreams.append(d_id)
        else:
            # If leaving DONE, clear completion timestamp and re-evaluate downstream cards
            if card.lane == KanbanLaneEnum.DONE:
                card.completed_at = None
                for other_card in board.cards.values():
                    if card_id in other_card.depends_on and other_card.lane not in (
                        KanbanLaneEnum.BACKLOG,
                        KanbanLaneEnum.BLOCKED,
                    ):
                        other_card.lane = KanbanLaneEnum.BLOCKED
                        other_card.blocked_by = KanbanTaskDagEngine.compute_blocked_status(
                            other_card, board.cards
                        )
                        other_card.updated_at = now

        card.lane = target_lane
        card.updated_at = now
        board.updated_at = now
        return card, unlocked_downstreams

    def mount_artifact(
        self,
        board_id: str,
        card_id: str,
        name: str,
        artifact_type: str = "file",
        file_path: str | None = None,
        content_preview: str | None = None,
    ) -> CardArtifactDTO:
        """Mount an execution output artifact (diff, test output, report) to a card."""
        board = self.get_board(board_id)
        if card_id not in board.cards:
            raise KanbanCardNotFoundError(f"Card '{card_id}' not found in board '{board_id}'.")

        card = board.cards[card_id]
        now = time.time()
        art = CardArtifactDTO(
            artifact_id=f"art-{uuid.uuid4().hex[:8]}",
            name=name,
            artifact_type=artifact_type,
            file_path=file_path,
            content_preview=content_preview,
            mounted_at=now,
        )
        card.artifacts.append(art)
        card.updated_at = now
        board.updated_at = now
        return art

    def human_override(
        self,
        board_id: str,
        card_id: str,
        new_agent: str | None = None,
        new_priority: CardPriorityEnum | None = None,
        new_lane: KanbanLaneEnum | None = None,
    ) -> tuple[KanbanCardDTO, list[str]]:
        """Human-in-the-loop override: reassign agent, update priority, or drag to lane."""
        board = self.get_board(board_id)
        if card_id not in board.cards:
            raise KanbanCardNotFoundError(f"Card '{card_id}' not found in board '{board_id}'.")

        card = board.cards[card_id]
        now = time.time()
        unlocked: list[str] = []

        if new_agent:
            card.assigned_agent = new_agent
        if new_priority:
            card.priority = new_priority
        if new_lane and new_lane != card.lane:
            card, unlocked = self.transition_card(board_id, card_id, new_lane, actor="human")

        card.updated_at = now
        board.updated_at = now
        return card, unlocked

    def auto_decompose_goal(
        self,
        board_id: str,
        goal: str,
        specialist_roster: list[str] | None = None,
    ) -> list[KanbanCardDTO]:
        """Boss Agent (Orchestrator) automated decomposition into sequenced DAG task cards."""
        roster = specialist_roster or ["@architect", "@backend-dev", "@frontend-dev", "@tester"]

        # Step 1: Design & Architecture (no dependencies)
        c1 = self.create_card(
            board_id=board_id,
            title=f"Architecture & Spec: {goal[:40]}",
            description=f"Design schema DTOs, API contracts, and DAG topology for '{goal}'.",
            assigned_agent=roster[0] if roster else "@architect",
            priority=CardPriorityEnum.HIGH,
            initial_lane=KanbanLaneEnum.TODO,
        )

        # Step 2: Implementation (depends on Step 1)
        c2 = self.create_card(
            board_id=board_id,
            title=f"Core Implementation: {goal[:40]}",
            description=f"Implement service domain logic and API routes for '{goal}'.",
            assigned_agent=roster[1 % len(roster)],
            depends_on=[c1.card_id],
            priority=CardPriorityEnum.HIGH,
        )

        # Step 3: Verification & Integration (depends on Step 2)
        c3 = self.create_card(
            board_id=board_id,
            title=f"Verification & Quality Gates: {goal[:40]}",
            description=f"Run test suites, linting, and verify zero-regression criteria for '{goal}'.",
            assigned_agent=roster[3 % len(roster)] if len(roster) > 3 else "@tester",
            depends_on=[c2.card_id],
            priority=CardPriorityEnum.MEDIUM,
        )

        return [c1, c2, c3]
