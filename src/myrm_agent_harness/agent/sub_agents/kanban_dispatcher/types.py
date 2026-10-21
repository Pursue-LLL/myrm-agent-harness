"""Type definitions for Visual Kanban Multi-Agent Workflow Dispatcher and Card Handoff (Item 66).

[INPUT]
- Kanban cards, column transitions, agent handoff events, and blocker alerts.

[OUTPUT]
- KanbanColumn, CardHandoffStatus, KanbanCard, HandoffEvent, KanbanWorkspaceState.

[POS]
- Harness orchestration layer for multi-agent kanban task dispatching and automated card handoffs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class KanbanColumn(StrEnum):
    """The five standard workflow stages in the multi-agent kanban board."""

    BACKLOG = "backlog"
    RESEARCHING = "researching"
    DEVELOPING = "developing"
    REVIEWING = "reviewing"
    DONE = "done"


class CardHandoffStatus(StrEnum):
    """Lifecycle and handoff state of a kanban task card."""

    IDLE = "idle"
    IN_TRANSIT = "in_transit"
    ACCEPTED = "accepted"
    BLOCKED = "blocked"
    COMPLETED = "completed"


@dataclass(slots=True)
class KanbanCard:
    """A discrete unit of work residing in a kanban column and assigned to an agent profile."""

    card_id: str
    title: str
    description: str
    column: KanbanColumn = KanbanColumn.BACKLOG
    assigned_agent_id: str = "product_manager"
    progress_percent: int = 0
    handoff_status: CardHandoffStatus = CardHandoffStatus.IDLE
    handoff_payload: dict[str, str] = field(default_factory=dict)
    blocker_reason: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class HandoffEvent:
    """Historical audit event recording an automated cross-agent card transition."""

    event_id: str
    card_id: str
    from_agent_id: str
    to_agent_id: str
    from_column: KanbanColumn
    to_column: KanbanColumn
    context_summary: str
    timestamp: float = field(default_factory=time.time)


@dataclass(slots=True)
class KanbanWorkspaceState:
    """Complete snapshot of a multi-agent kanban workspace."""

    workspace_id: str
    title: str
    cards: list[KanbanCard] = field(default_factory=list)
    handoff_history: list[HandoffEvent] = field(default_factory=list)
    active_blockers: int = 0
