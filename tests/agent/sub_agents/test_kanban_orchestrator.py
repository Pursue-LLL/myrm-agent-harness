"""Unit tests for Multi-Agent Kanban Orchestrator and Card Lifecycle Dispatcher."""

import pytest

from myrm_agent_harness.agent.sub_agents.kanban_orchestrator import (
    CardPriorityEnum,
    KanbanBlockedCardError,
    KanbanCardLifecycleDispatcher,
    KanbanCardNotFoundError,
    KanbanDependencyCycleError,
    KanbanLaneEnum,
    KanbanTaskDagEngine,
)


@pytest.fixture
def dispatcher() -> KanbanCardLifecycleDispatcher:
    disp = KanbanCardLifecycleDispatcher()
    disp.create_board(board_id="board-test-1", session_id="chat-1", title="Feature Alpha Kanban")
    return disp


def test_board_creation_and_card_sandbox_allocation(dispatcher: KanbanCardLifecycleDispatcher):
    card = dispatcher.create_card(
        board_id="board-test-1",
        title="Setup database schema",
        description="Write migration and models",
        assigned_agent="@backend-dev",
        priority=CardPriorityEnum.HIGH,
    )

    assert card.board_id == "board-test-1"
    assert card.lane == KanbanLaneEnum.TODO
    assert card.sandbox_subdir == f"tasks/{card.card_id}"
    assert len(card.depends_on) == 0
    assert len(card.blocked_by) == 0


def test_dependency_cycle_detection(dispatcher: KanbanCardLifecycleDispatcher):
    c1 = dispatcher.create_card(
        board_id="board-test-1",
        title="Step 1",
        description="First step",
        assigned_agent="@architect",
    )
    c2 = dispatcher.create_card(
        board_id="board-test-1",
        title="Step 2",
        description="Second step",
        assigned_agent="@backend-dev",
        depends_on=[c1.card_id],
    )

    # Non-existent prerequisite card must raise KanbanCardNotFoundError
    with pytest.raises(KanbanCardNotFoundError):
        dispatcher.create_card(
            board_id="board-test-1",
            title="Non-existent dep",
            description="Bad",
            assigned_agent="@tester",
            depends_on=["non_existent_card_id"],
        )

    # Test direct cycle detection via DAG engine (c1 -> c2 -> c1)
    c1.depends_on = [c2.card_id]
    cards_map = {c1.card_id: c1, c2.card_id: c2}
    with pytest.raises(KanbanDependencyCycleError, match="Cyclic dependency detected"):
        KanbanTaskDagEngine.validate_dependencies(cards_map)


def test_blocked_card_automatic_state_and_forbidden_execution(
    dispatcher: KanbanCardLifecycleDispatcher,
):
    c1 = dispatcher.create_card(
        board_id="board-test-1",
        title="Prerequisite Core API",
        description="Build core endpoints",
        assigned_agent="@backend-dev",
    )
    # c2 depends on c1, which is in TODO (not DONE)
    c2 = dispatcher.create_card(
        board_id="board-test-1",
        title="Downstream Integration Test",
        description="Test core endpoints",
        assigned_agent="@tester",
        depends_on=[c1.card_id],
    )

    # c2 must be BLOCKED initially
    assert c2.lane == KanbanLaneEnum.BLOCKED
    assert c1.card_id in c2.blocked_by

    # Attempting to start execution on a blocked card must fail
    with pytest.raises(KanbanBlockedCardError):
        dispatcher.transition_card(
            board_id="board-test-1",
            card_id=c2.card_id,
            target_lane=KanbanLaneEnum.IN_PROGRESS,
        )


def test_auto_unblock_cascade_upon_prerequisite_done(
    dispatcher: KanbanCardLifecycleDispatcher,
):
    c1 = dispatcher.create_card(
        board_id="board-test-1",
        title="Card 1: Spec",
        description="Design system spec",
        assigned_agent="@architect",
    )
    c2 = dispatcher.create_card(
        board_id="board-test-1",
        title="Card 2: Code",
        description="Write React components",
        assigned_agent="@frontend-dev",
        depends_on=[c1.card_id],
    )

    assert c2.lane == KanbanLaneEnum.BLOCKED
    assert c1.card_id in c2.blocked_by

    # Move c1 to IN_PROGRESS
    dispatcher.transition_card("board-test-1", c1.card_id, KanbanLaneEnum.IN_PROGRESS)
    assert c2.lane == KanbanLaneEnum.BLOCKED

    # Move c1 to DONE -> triggers auto-unblock cascade!
    updated_c1, unlocked = dispatcher.transition_card(
        "board-test-1", c1.card_id, KanbanLaneEnum.DONE
    )
    assert updated_c1.lane == KanbanLaneEnum.DONE
    assert updated_c1.completed_at is not None
    assert c2.card_id in unlocked

    # Check that c2 has been unlocked to TODO
    board = dispatcher.get_board("board-test-1")
    c2_ref = board.cards[c2.card_id]
    assert c2_ref.lane == KanbanLaneEnum.TODO
    assert len(c2_ref.blocked_by) == 0

    # Now c2 can transition to IN_PROGRESS
    updated_c2, _ = dispatcher.transition_card(
        "board-test-1", c2.card_id, KanbanLaneEnum.IN_PROGRESS
    )
    assert updated_c2.lane == KanbanLaneEnum.IN_PROGRESS


def test_mount_artifact_and_human_override(dispatcher: KanbanCardLifecycleDispatcher):
    card = dispatcher.create_card(
        board_id="board-test-1",
        title="Frontend styling",
        description="Implement tailwind classes",
        assigned_agent="@frontend-dev",
        priority=CardPriorityEnum.LOW,
    )

    # Mount artifact
    art = dispatcher.mount_artifact(
        board_id="board-test-1",
        card_id=card.card_id,
        name="Header.tsx Diff",
        artifact_type="diff",
        file_path="src/components/Header.tsx",
        content_preview="@@ -10,3 +10,3 @@ bg-primary",
    )
    assert art.artifact_id.startswith("art-")
    assert len(card.artifacts) == 1
    assert card.artifacts[0].file_path == "src/components/Header.tsx"

    # Human-in-the-loop override
    updated, _ = dispatcher.human_override(
        board_id="board-test-1",
        card_id=card.card_id,
        new_agent="@lead-architect",
        new_priority=CardPriorityEnum.CRITICAL,
        new_lane=KanbanLaneEnum.REVIEW,
    )
    assert updated.assigned_agent == "@lead-architect"
    assert updated.priority == CardPriorityEnum.CRITICAL
    assert updated.lane == KanbanLaneEnum.REVIEW


def test_auto_decompose_goal_into_dag_pipeline(dispatcher: KanbanCardLifecycleDispatcher):
    cards = dispatcher.auto_decompose_goal(
        board_id="board-test-1",
        goal="Build real-time notification service",
        specialist_roster=["@architect", "@backend-dev", "@frontend-dev", "@tester"],
    )

    assert len(cards) == 3
    c1, c2, c3 = cards

    assert c1.lane == KanbanLaneEnum.TODO
    assert c2.lane == KanbanLaneEnum.BLOCKED
    assert c3.lane == KanbanLaneEnum.BLOCKED

    assert c1.card_id in c2.depends_on
    assert c2.card_id in c3.depends_on

    # Verify topological order
    board = dispatcher.get_board("board-test-1")
    sorted_ids = KanbanTaskDagEngine.topological_sort(board.cards)
    assert sorted_ids.index(c1.card_id) < sorted_ids.index(c2.card_id) < sorted_ids.index(c3.card_id)
