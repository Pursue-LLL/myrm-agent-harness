"""Durable Agent Teams orchestration package.

[INPUT]
- .types::*
- .task_graph::TaskGraphEngine
- .mailbox::DurablePeerMailbox
- .engine::DurableAgentTeamEngine

[OUTPUT]
- Public export of types, engines, and errors for Durable Agent Teams

[POS]
Topic 12 #28 DurableAgentTeamsPeerMailboxAndSharedTaskDagKanban
"""

from .engine import DurableAgentTeamEngine
from .mailbox import DurablePeerMailbox
from .task_graph import TaskGraphEngine
from .types import (
    CASConflictError,
    DeliveryMode,
    TaskBlockedError,
    TaskDependencyCycleError,
    TeamMemberPhase,
    TeamMemberRole,
    TeamMemberSnapshot,
    TeamMessageSnapshot,
    TeamProjection,
    TeamTaskSnapshot,
    TeamTaskStatus,
    TeamTaskView,
)

__all__ = [
    "CASConflictError",
    "DeliveryMode",
    "DurableAgentTeamEngine",
    "DurablePeerMailbox",
    "TaskBlockedError",
    "TaskDependencyCycleError",
    "TaskGraphEngine",
    "TeamMemberPhase",
    "TeamMemberRole",
    "TeamMemberSnapshot",
    "TeamMessageSnapshot",
    "TeamProjection",
    "TeamTaskSnapshot",
    "TeamTaskStatus",
    "TeamTaskView",
]
