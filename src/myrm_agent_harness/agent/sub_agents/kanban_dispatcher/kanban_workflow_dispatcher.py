"""Visual Kanban Multi-Agent Workflow Dispatcher and Card Handoff engine (Item 66).

[INPUT]
- Kanban card lifecycle operations, column transitions, and blocker events.

[OUTPUT]
- KanbanCard updates, HandoffEvent audit logs, KanbanWorkspaceState snapshots.

[POS]
- Harness orchestration layer for multi-agent kanban task dispatching and automated card handoffs.
"""

from __future__ import annotations

import time
import uuid

from myrm_agent_harness.agent.sub_agents.kanban_dispatcher.types import (
    CardHandoffStatus,
    HandoffEvent,
    KanbanCard,
    KanbanColumn,
    KanbanWorkspaceState,
)

DEFAULT_COLUMN_AGENTS: dict[KanbanColumn, str] = {
    KanbanColumn.BACKLOG: "product_manager",
    KanbanColumn.RESEARCHING: "research_specialist",
    KanbanColumn.DEVELOPING: "dev_coder",
    KanbanColumn.REVIEWING: "reviewer_critic",
    KanbanColumn.DONE: "qa_release_bot",
}


class KanbanWorkflowDispatcher:
    """Manages multi-agent kanban board columns, automated cross-agent handoffs, and blocker tracking."""

    def __init__(self) -> None:
        self._workspaces: dict[str, KanbanWorkspaceState] = {}

    def _ensure_workspace(self, workspace_id: str, title: str = "Default Workspace") -> KanbanWorkspaceState:
        ws = self._workspaces.get(workspace_id)
        if ws is None:
            ws = KanbanWorkspaceState(
                workspace_id=workspace_id,
                title=title,
                cards=[],
                handoff_history=[],
                active_blockers=0,
            )
            self._workspaces[workspace_id] = ws
        return ws

    def create_card(
        self,
        workspace_id: str,
        title: str,
        description: str,
        column: KanbanColumn = KanbanColumn.BACKLOG,
        assigned_agent_id: str | None = None,
    ) -> KanbanCard:
        """Create a new work item card in the kanban workspace."""
        ws = self._ensure_workspace(workspace_id)
        card_id = f"card_{uuid.uuid4().hex[:8]}"
        agent_id = assigned_agent_id or DEFAULT_COLUMN_AGENTS.get(column, "product_manager")

        card = KanbanCard(
            card_id=card_id,
            title=title,
            description=description,
            column=column,
            assigned_agent_id=agent_id,
            progress_percent=0,
            handoff_status=CardHandoffStatus.IDLE,
            handoff_payload={},
            blocker_reason=None,
            created_at=time.time(),
            updated_at=time.time(),
        )
        ws.cards.append(card)
        return card

    def get_card(self, workspace_id: str, card_id: str) -> KanbanCard | None:
        """Retrieve a specific card from the workspace."""
        ws = self._workspaces.get(workspace_id)
        if ws is None:
            return None
        for c in ws.cards:
            if c.card_id == card_id:
                return c
        return None

    def list_cards(
        self,
        workspace_id: str,
        column: KanbanColumn | None = None,
    ) -> list[KanbanCard]:
        """List all cards in a workspace, optionally filtered by column."""
        ws = self._ensure_workspace(workspace_id)
        if column is None:
            return list(ws.cards)
        return [c for c in ws.cards if c.column == column]

    def transition_card(
        self,
        workspace_id: str,
        card_id: str,
        target_column: KanbanColumn,
        handoff_context: dict[str, str] | None = None,
        target_agent_id: str | None = None,
    ) -> KanbanCard:
        """Move card to a new column, trigger cross-agent packaging, and record a handoff event."""
        ws = self._ensure_workspace(workspace_id)
        card = self.get_card(workspace_id, card_id)
        if card is None:
            raise KeyError(f"Card '{card_id}' not found in workspace '{workspace_id}'.")

        old_column = card.column
        old_agent = card.assigned_agent_id
        new_agent = target_agent_id or DEFAULT_COLUMN_AGENTS.get(target_column, old_agent)

        # Update card fields
        card.column = target_column
        card.assigned_agent_id = new_agent
        card.handoff_status = (
            CardHandoffStatus.COMPLETED
            if target_column == KanbanColumn.DONE
            else CardHandoffStatus.ACCEPTED
        )
        if handoff_context:
            card.handoff_payload.update(handoff_context)
        if target_column == KanbanColumn.DONE:
            card.progress_percent = 100
        card.updated_at = time.time()

        # Audit handoff event
        event = HandoffEvent(
            event_id=f"event_{uuid.uuid4().hex[:8]}",
            card_id=card_id,
            from_agent_id=old_agent,
            to_agent_id=new_agent,
            from_column=old_column,
            to_column=target_column,
            context_summary=f"Transferred from {old_agent} to {new_agent} on stage {target_column.value}.",
            timestamp=time.time(),
        )
        ws.handoff_history.append(event)
        return card

    def update_progress(
        self,
        workspace_id: str,
        card_id: str,
        progress_percent: int,
    ) -> KanbanCard:
        """Update the real-time execution progress percent of a card."""
        card = self.get_card(workspace_id, card_id)
        if card is None:
            raise KeyError(f"Card '{card_id}' not found in workspace '{workspace_id}'.")
        card.progress_percent = max(0, min(100, progress_percent))
        card.updated_at = time.time()
        return card

    def flag_blocker(
        self,
        workspace_id: str,
        card_id: str,
        reason: str,
    ) -> KanbanCard:
        """Mark a card as blocked (e.g. awaiting HITL human approval or external service outage)."""
        ws = self._ensure_workspace(workspace_id)
        card = self.get_card(workspace_id, card_id)
        if card is None:
            raise KeyError(f"Card '{card_id}' not found in workspace '{workspace_id}'.")
        card.handoff_status = CardHandoffStatus.BLOCKED
        card.blocker_reason = reason
        card.updated_at = time.time()
        ws.active_blockers = sum(
            1 for c in ws.cards if c.handoff_status == CardHandoffStatus.BLOCKED
        )
        return card

    def resolve_blocker(
        self,
        workspace_id: str,
        card_id: str,
    ) -> KanbanCard:
        """Resolve an active blocker on a card and restore its accepted execution status."""
        ws = self._ensure_workspace(workspace_id)
        card = self.get_card(workspace_id, card_id)
        if card is None:
            raise KeyError(f"Card '{card_id}' not found in workspace '{workspace_id}'.")
        card.handoff_status = CardHandoffStatus.ACCEPTED
        card.blocker_reason = None
        card.updated_at = time.time()
        ws.active_blockers = sum(
            1 for c in ws.cards if c.handoff_status == CardHandoffStatus.BLOCKED
        )
        return card

    def get_workspace_state(self, workspace_id: str) -> KanbanWorkspaceState:
        """Return the complete snapshot of a kanban workspace."""
        ws = self._ensure_workspace(workspace_id)
        ws.active_blockers = sum(
            1 for c in ws.cards if c.handoff_status == CardHandoffStatus.BLOCKED
        )
        return ws

    def clear(self) -> None:
        """Clear all workspace states (used for test isolation)."""
        self._workspaces.clear()
