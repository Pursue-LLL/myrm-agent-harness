"""Unit tests for Visual Kanban Multi-Agent Workflow Dispatcher and Card Handoff (Item 66).

[INPUT]
- KanbanWorkflowDispatcher, KanbanCard, KanbanColumn, CardHandoffStatus.

[OUTPUT]
- Pytest assertions verifying card creation, automated agent handoffs across columns,
  blocker flagging/resolving, progress tracking, and audit event logs.

[POS]
- myrm-agent-harness/tests/agent/sub_agents/test_kanban_dispatcher.py
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.sub_agents.kanban_dispatcher import (
    CardHandoffStatus,
    KanbanColumn,
    KanbanWorkflowDispatcher,
)


@pytest.fixture
def dispatcher() -> KanbanWorkflowDispatcher:
    """Fixture providing a fresh KanbanWorkflowDispatcher."""
    disp = KanbanWorkflowDispatcher()
    disp.clear()
    return disp


def test_create_card_and_default_agent(dispatcher: KanbanWorkflowDispatcher) -> None:
    """Verify card creation assigns correct default column agents."""
    c1 = dispatcher.create_card(
        workspace_id="ws-test",
        title="Implement Auth Token Rotation",
        description="JWT refresh token rotation protocol",
    )
    assert c1.column == KanbanColumn.BACKLOG
    assert c1.assigned_agent_id == "product_manager"
    assert c1.progress_percent == 0
    assert c1.handoff_status == CardHandoffStatus.IDLE

    c2 = dispatcher.create_card(
        workspace_id="ws-test",
        title="Research Vector Indexing",
        description="Benchmark HNSW vs IVF",
        column=KanbanColumn.RESEARCHING,
    )
    assert c2.column == KanbanColumn.RESEARCHING
    assert c2.assigned_agent_id == "research_specialist"


def test_list_cards_and_filtering(dispatcher: KanbanWorkflowDispatcher) -> None:
    """Verify card listing and column-based filtering."""
    dispatcher.create_card("ws-list", "Task 1", "Desc 1", KanbanColumn.BACKLOG)
    dispatcher.create_card("ws-list", "Task 2", "Desc 2", KanbanColumn.DEVELOPING)
    dispatcher.create_card("ws-list", "Task 3", "Desc 3", KanbanColumn.DEVELOPING)

    all_cards = dispatcher.list_cards("ws-list")
    assert len(all_cards) == 3

    dev_cards = dispatcher.list_cards("ws-list", column=KanbanColumn.DEVELOPING)
    assert len(dev_cards) == 2
    assert all(c.column == KanbanColumn.DEVELOPING for c in dev_cards)


def test_transition_card_automated_handoff(dispatcher: KanbanWorkflowDispatcher) -> None:
    """Verify column transition automatically reassigns agent and records handoff event."""
    c = dispatcher.create_card("ws-flow", "API Gateway Migration", "Migrate to Envoy")
    card_id = c.card_id

    # Transition from BACKLOG -> DEVELOPING with context
    updated = dispatcher.transition_card(
        workspace_id="ws-flow",
        card_id=card_id,
        target_column=KanbanColumn.DEVELOPING,
        handoff_context={"spec_doc": "doc://specs/envoy.md", "branch": "feature/envoy"},
    )
    assert updated.column == KanbanColumn.DEVELOPING
    assert updated.assigned_agent_id == "dev_coder"
    assert updated.handoff_status == CardHandoffStatus.ACCEPTED
    assert updated.handoff_payload.get("spec_doc") == "doc://specs/envoy.md"

    ws_state = dispatcher.get_workspace_state("ws-flow")
    assert len(ws_state.handoff_history) == 1
    event = ws_state.handoff_history[0]
    assert event.card_id == card_id
    assert event.from_agent_id == "product_manager"
    assert event.to_agent_id == "dev_coder"
    assert event.from_column == KanbanColumn.BACKLOG
    assert event.to_column == KanbanColumn.DEVELOPING

    # Transition to DONE
    done_card = dispatcher.transition_card(
        workspace_id="ws-flow",
        card_id=card_id,
        target_column=KanbanColumn.DONE,
    )
    assert done_card.column == KanbanColumn.DONE
    assert done_card.assigned_agent_id == "qa_release_bot"
    assert done_card.handoff_status == CardHandoffStatus.COMPLETED
    assert done_card.progress_percent == 100
    assert len(ws_state.handoff_history) == 2


def test_update_progress(dispatcher: KanbanWorkflowDispatcher) -> None:
    """Verify progress updates with upper and lower boundary clamping."""
    c = dispatcher.create_card("ws-prog", "Write Tests", "Coverage >90%")
    card_id = c.card_id

    dispatcher.update_progress("ws-prog", card_id, 45)
    card = dispatcher.get_card("ws-prog", card_id)
    assert card is not None
    assert card.progress_percent == 45

    dispatcher.update_progress("ws-prog", card_id, 150)
    assert card.progress_percent == 100

    dispatcher.update_progress("ws-prog", card_id, -10)
    assert card.progress_percent == 0


def test_flag_and_resolve_blocker(dispatcher: KanbanWorkflowDispatcher) -> None:
    """Verify blocker detection, active_blockers count, and resolution."""
    c = dispatcher.create_card("ws-block", "Deploy Production", "Deploy v2.0")
    card_id = c.card_id

    # Flag blocker
    blocked_card = dispatcher.flag_blocker(
        "ws-block",
        card_id,
        reason="Requires HITL Human Approval for High-Risk Migration",
    )
    assert blocked_card.handoff_status == CardHandoffStatus.BLOCKED
    assert "HITL Human Approval" in (blocked_card.blocker_reason or "")

    ws_state = dispatcher.get_workspace_state("ws-block")
    assert ws_state.active_blockers == 1

    # Resolve blocker
    resolved_card = dispatcher.resolve_blocker("ws-block", card_id)
    assert resolved_card.handoff_status == CardHandoffStatus.ACCEPTED
    assert resolved_card.blocker_reason is None

    ws_state_resolved = dispatcher.get_workspace_state("ws-block")
    assert ws_state_resolved.active_blockers == 0


def test_get_card_not_found_and_transition_keyerror(dispatcher: KanbanWorkflowDispatcher) -> None:
    """Verify graceful None on missing card and KeyError on invalid transitions."""
    assert dispatcher.get_card("non-existent-ws", "fake-card") is None

    with pytest.raises(KeyError, match="not found"):
        dispatcher.transition_card("ws", "fake-card", KanbanColumn.DONE)

    with pytest.raises(KeyError, match="not found"):
        dispatcher.update_progress("ws", "fake-card", 50)

    with pytest.raises(KeyError, match="not found"):
        dispatcher.flag_blocker("ws", "fake-card", "broken")

    with pytest.raises(KeyError, match="not found"):
        dispatcher.resolve_blocker("ws", "fake-card")


def test_clear_workspaces(dispatcher: KanbanWorkflowDispatcher) -> None:
    """Verify clear resets all internal state."""
    dispatcher.create_card("ws-clr", "Task", "Desc")
    assert len(dispatcher.list_cards("ws-clr")) == 1

    dispatcher.clear()
    assert len(dispatcher.list_cards("ws-clr")) == 0
