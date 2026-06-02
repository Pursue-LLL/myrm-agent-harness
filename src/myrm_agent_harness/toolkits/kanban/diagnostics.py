"""Kanban task diagnostic framework.

Pure DTOs, rule protocol, and engine for detecting task anomalies.
Zero I/O — all data is passed in; rules are pure functions.

[INPUT]
- .types (POS: Kanban domain types.)

[OUTPUT]
- TaskDiagnosticSeverity: warning / error / critical
- DiagnosticAction: Suggested recovery step
- TaskDiagnostic: Single detected issue for a task
- DiagnosticRule: Protocol for pluggable diagnostic rules
- DiagnosticContext: Extra data for rules needing more than task fields
- DiagnosticEngine: Executes registered rules, collects & sorts diagnostics

[POS]
Kanban task diagnostic framework.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from myrm_agent_harness.toolkits.kanban.types import KanbanTask


class TaskDiagnosticSeverity(StrEnum):
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


_SEVERITY_ORDER: dict[TaskDiagnosticSeverity, int] = {
    TaskDiagnosticSeverity.CRITICAL: 0,
    TaskDiagnosticSeverity.ERROR: 1,
    TaskDiagnosticSeverity.WARNING: 2,
}


@dataclass(frozen=True, slots=True)
class DiagnosticAction:
    """A suggested recovery action attached to a diagnostic.

    Attributes:
        kind: Machine-readable action type (e.g. ``move_to_ready``, ``retry``).
        label: Human-readable button label.
        payload: Arbitrary data the frontend/caller needs to execute the action.
        suggested: Whether the UI should highlight this as the recommended action.
    """

    kind: str
    label: str
    payload: dict[str, str] = field(default_factory=dict)
    suggested: bool = False


@dataclass(frozen=True, slots=True)
class TaskDiagnostic:
    """A single detected issue for a task.

    Attributes:
        rule_id: Machine-readable rule identifier (e.g. ``stuck_in_blocked``).
        severity: Severity level of the issue.
        title: Short human-readable summary.
        detail: Longer explanation with context.
        actions: Suggested recovery steps.
    """

    rule_id: str
    severity: TaskDiagnosticSeverity
    title: str
    detail: str
    actions: tuple[DiagnosticAction, ...] = ()


@dataclass(frozen=True, slots=True)
class DiagnosticContext:
    """Extra data passed to rules that need more than task fields.

    Populated by the server layer before calling the engine.
    Only filled for single-task (drawer-level) diagnostics.
    """

    parent_task_ids: tuple[str, ...] = ()
    parent_statuses: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class DiagnosticRule(Protocol):
    """Protocol for a pluggable diagnostic rule.

    Each rule inspects a task (and optional context) and returns
    zero or more diagnostics. Rules must be stateless and side-effect-free.
    """

    @property
    def rule_id(self) -> str: ...

    def evaluate(
        self,
        task: KanbanTask,
        *,
        context: DiagnosticContext | None = None,
    ) -> list[TaskDiagnostic]: ...


class DiagnosticEngine:
    """Executes registered rules against a task, collects and sorts results.

    Thread-safe: rules list is append-only after construction.
    """

    __slots__ = ("_rules",)

    def __init__(self) -> None:
        self._rules: list[DiagnosticRule] = []

    def register(self, rule: DiagnosticRule) -> None:
        self._rules.append(rule)

    def evaluate(
        self,
        task: KanbanTask,
        *,
        context: DiagnosticContext | None = None,
        rule_ids: frozenset[str] | None = None,
    ) -> list[TaskDiagnostic]:
        """Run rules against a task and return diagnostics sorted by severity.

        Args:
            task: The task to diagnose.
            context: Optional extra data for rules that need it.
            rule_ids: If provided, only run rules with matching IDs (for fast-path).
        """
        diagnostics: list[TaskDiagnostic] = []
        for rule in self._rules:
            if rule_ids is not None and rule.rule_id not in rule_ids:
                continue
            with contextlib.suppress(Exception):
                diagnostics.extend(rule.evaluate(task, context=context))
        diagnostics.sort(key=lambda d: _SEVERITY_ORDER.get(d.severity, 99))
        return diagnostics

    @property
    def rule_ids(self) -> list[str]:
        return [r.rule_id for r in self._rules]
