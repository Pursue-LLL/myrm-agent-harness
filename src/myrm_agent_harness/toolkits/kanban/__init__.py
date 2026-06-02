"""Kanban multi-task scheduling toolkit.

Protocol-first design: the framework defines dispatch logic, CRUD management,
agent tools, and 2 protocols.  Concrete storage backends and task runners
are injected by the application layer.

Provides:
- KanbanDispatcher: event-driven multi-task scheduler with heartbeat/zombie/auto-block
- KanbanStore: persistence protocol (boards, tasks, claims, runs, events)
- TaskRunner: task execution protocol
- InMemoryKanbanStore: built-in in-memory store for development and testing
- build_task_context: worker context assembly helper for TaskRunner implementors
- Domain types: KanbanBoard, KanbanTask, TaskEdge, TaskStatus, TaskPriority, BlockKind,
  BoardSettings, TaskClaim, TaskRun, TaskRunOutcome, TaskEvent, TaskEventKind
- create_kanban_tools: agent tool factory
- get_worker_lifecycle_guidance: pure function for worker system prompt injection

[INPUT]
- .dispatcher::KanbanDispatcher (POS: Event-driven multi-task scheduler.)
- .kanban_agent_tools::create_kanban_tools (POS: Agent tools for kanban task management.)
- .protocols (POS: Protocols for the kanban toolkit.)
- .stores::InMemoryKanbanStore (POS: In-memory KanbanStore implementation.)
- .types (POS: Kanban domain types.)

[OUTPUT]
- KanbanDispatcher, KanbanStore, TaskRunner: core components
- InMemoryKanbanStore: built-in reference store
- Domain types: KanbanBoard, KanbanTask, TaskEdge, TaskStatus, TaskPriority,
  BoardSettings, TaskClaim, TaskRun, TaskRunOutcome, TaskEvent, TaskEventKind
- create_kanban_tools: agent tool factory
- get_worker_lifecycle_guidance: worker lifecycle guidance generator

[POS]
Kanban toolkit entry point. Aggregates dispatcher, protocols, built-in
implementations, and data models for the protocol-first kanban framework.
"""

from myrm_agent_harness.toolkits.kanban.context_builder import (
    build_multimodal_query,
    build_task_context,
)
from myrm_agent_harness.toolkits.kanban.diagnostics import (
    DiagnosticAction,
    DiagnosticContext,
    DiagnosticEngine,
    DiagnosticRule,
    TaskDiagnostic,
    TaskDiagnosticSeverity,
)
from myrm_agent_harness.toolkits.kanban.dispatcher import KanbanDispatcher
from myrm_agent_harness.toolkits.kanban.kanban_agent_tools import (
    KanbanToolMode,
    create_kanban_tools,
    get_worker_lifecycle_guidance,
)
from myrm_agent_harness.toolkits.kanban.protocols import (
    KanbanStore,
    SpecifyOutcome,
    TaskRunner,
    TaskSpecifier,
)
from myrm_agent_harness.toolkits.kanban.stores import InMemoryKanbanStore
from myrm_agent_harness.toolkits.kanban.types import (
    BlockKind,
    BoardSettings,
    KanbanBoard,
    KanbanTask,
    TaskAttachment,
    TaskClaim,
    TaskEdge,
    TaskEvent,
    TaskEventKind,
    TaskPriority,
    TaskRun,
    TaskRunOutcome,
    TaskStatus,
    TaskTimeoutError,
)

__all__ = [
    "BlockKind",
    "BoardSettings",
    "DiagnosticAction",
    "DiagnosticContext",
    "DiagnosticEngine",
    "DiagnosticRule",
    "InMemoryKanbanStore",
    "KanbanBoard",
    "KanbanDispatcher",
    "KanbanStore",
    "KanbanTask",
    "KanbanToolMode",
    "SpecifyOutcome",
    "TaskAttachment",
    "TaskClaim",
    "TaskDiagnostic",
    "TaskDiagnosticSeverity",
    "TaskEdge",
    "TaskEvent",
    "TaskEventKind",
    "TaskPriority",
    "TaskRun",
    "TaskRunOutcome",
    "TaskRunner",
    "TaskSpecifier",
    "TaskStatus",
    "TaskTimeoutError",
    "build_multimodal_query",
    "build_task_context",
    "create_kanban_tools",
    "get_worker_lifecycle_guidance",
]
