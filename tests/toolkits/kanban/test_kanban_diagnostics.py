"""Tests for kanban task diagnostic framework (harness layer).

Covers DTOs, engine, rule protocol, and severity ordering.
Target: ≥80% coverage for myrm_agent_harness.toolkits.kanban.diagnostics.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.toolkits.kanban.diagnostics import (
    _SEVERITY_ORDER,
    DiagnosticAction,
    DiagnosticContext,
    DiagnosticEngine,
    DiagnosticRule,
    TaskDiagnostic,
    TaskDiagnosticSeverity,
)
from myrm_agent_harness.toolkits.kanban.types import (
    KanbanTask,
    TaskPriority,
    TaskStatus,
)


def _make_task(
    *,
    status: TaskStatus = TaskStatus.READY,
    consecutive_failures: int = 0,
    blocked_reason: str | None = None,
    error: str = "",
    hours_ago: float = 0,
) -> KanbanTask:
    ts = datetime.now(UTC) - timedelta(hours=hours_ago)
    return KanbanTask(
        task_id="t1",
        board_id="b1",
        title="Test Task",
        status=status,
        priority=TaskPriority.NORMAL,
        consecutive_failures=consecutive_failures,
        blocked_reason=blocked_reason,
        error=error,
        updated_at=ts,
        created_at=ts,
    )


# ---------------------------------------------------------------------------
# DTO tests
# ---------------------------------------------------------------------------


class TestTaskDiagnosticSeverity:
    def test_values(self) -> None:
        assert TaskDiagnosticSeverity.WARNING == "warning"
        assert TaskDiagnosticSeverity.ERROR == "error"
        assert TaskDiagnosticSeverity.CRITICAL == "critical"

    def test_severity_order_covers_all(self) -> None:
        for sev in TaskDiagnosticSeverity:
            assert sev in _SEVERITY_ORDER

    def test_severity_order_critical_highest(self) -> None:
        assert _SEVERITY_ORDER[TaskDiagnosticSeverity.CRITICAL] < _SEVERITY_ORDER[TaskDiagnosticSeverity.ERROR]
        assert _SEVERITY_ORDER[TaskDiagnosticSeverity.ERROR] < _SEVERITY_ORDER[TaskDiagnosticSeverity.WARNING]


class TestDiagnosticAction:
    def test_frozen(self) -> None:
        action = DiagnosticAction(kind="archive", label="Archive", payload={"target_status": "archived"})
        with pytest.raises(AttributeError):
            action.kind = "other"  # type: ignore[misc]

    def test_default_payload_and_suggested(self) -> None:
        action = DiagnosticAction(kind="test", label="Test")
        assert action.payload == {}
        assert action.suggested is False

    def test_suggested_flag(self) -> None:
        action = DiagnosticAction(kind="retry", label="Retry", suggested=True)
        assert action.suggested is True


class TestTaskDiagnostic:
    def test_frozen(self) -> None:
        diag = TaskDiagnostic(
            rule_id="test_rule",
            severity=TaskDiagnosticSeverity.WARNING,
            title="Test",
            detail="Detail",
        )
        with pytest.raises(AttributeError):
            diag.rule_id = "other"  # type: ignore[misc]

    def test_default_actions_empty(self) -> None:
        diag = TaskDiagnostic(
            rule_id="r", severity=TaskDiagnosticSeverity.WARNING, title="T", detail="D"
        )
        assert diag.actions == ()

    def test_with_actions(self) -> None:
        action = DiagnosticAction(kind="archive", label="Archive")
        diag = TaskDiagnostic(
            rule_id="r",
            severity=TaskDiagnosticSeverity.ERROR,
            title="T",
            detail="D",
            actions=(action,),
        )
        assert len(diag.actions) == 1
        assert diag.actions[0].kind == "archive"


class TestDiagnosticContext:
    def test_frozen(self) -> None:
        ctx = DiagnosticContext(parent_task_ids=("p1",), parent_statuses={"p1": "failed"})
        with pytest.raises(AttributeError):
            ctx.parent_task_ids = ()  # type: ignore[misc]

    def test_defaults_empty(self) -> None:
        ctx = DiagnosticContext()
        assert ctx.parent_task_ids == ()
        assert ctx.parent_statuses == {}


# ---------------------------------------------------------------------------
# DiagnosticRule Protocol tests
# ---------------------------------------------------------------------------


class TestDiagnosticRuleProtocol:
    def test_conformant_class(self) -> None:
        class GoodRule:
            @property
            def rule_id(self) -> str:
                return "good"

            def evaluate(
                self,
                task: KanbanTask,
                *,
                context: DiagnosticContext | None = None,
            ) -> list[TaskDiagnostic]:
                return []

        assert isinstance(GoodRule(), DiagnosticRule)

    def test_non_conformant_class(self) -> None:
        class BadRule:
            pass

        assert not isinstance(BadRule(), DiagnosticRule)


# ---------------------------------------------------------------------------
# DiagnosticEngine tests
# ---------------------------------------------------------------------------


class _WarningRule:
    @property
    def rule_id(self) -> str:
        return "warn_rule"

    def evaluate(
        self, task: KanbanTask, *, context: DiagnosticContext | None = None
    ) -> list[TaskDiagnostic]:
        return [
            TaskDiagnostic(
                rule_id=self.rule_id,
                severity=TaskDiagnosticSeverity.WARNING,
                title="Warning",
                detail="A warning",
            )
        ]


class _ErrorRule:
    @property
    def rule_id(self) -> str:
        return "err_rule"

    def evaluate(
        self, task: KanbanTask, *, context: DiagnosticContext | None = None
    ) -> list[TaskDiagnostic]:
        return [
            TaskDiagnostic(
                rule_id=self.rule_id,
                severity=TaskDiagnosticSeverity.ERROR,
                title="Error",
                detail="An error",
            )
        ]


class _CriticalRule:
    @property
    def rule_id(self) -> str:
        return "crit_rule"

    def evaluate(
        self, task: KanbanTask, *, context: DiagnosticContext | None = None
    ) -> list[TaskDiagnostic]:
        return [
            TaskDiagnostic(
                rule_id=self.rule_id,
                severity=TaskDiagnosticSeverity.CRITICAL,
                title="Critical",
                detail="A critical",
            )
        ]


class _ExplodingRule:
    @property
    def rule_id(self) -> str:
        return "exploding"

    def evaluate(
        self, task: KanbanTask, *, context: DiagnosticContext | None = None
    ) -> list[TaskDiagnostic]:
        raise RuntimeError("boom")


class _EmptyRule:
    @property
    def rule_id(self) -> str:
        return "empty_rule"

    def evaluate(
        self, task: KanbanTask, *, context: DiagnosticContext | None = None
    ) -> list[TaskDiagnostic]:
        return []


class _ContextAwareRule:
    @property
    def rule_id(self) -> str:
        return "context_aware"

    def evaluate(
        self, task: KanbanTask, *, context: DiagnosticContext | None = None
    ) -> list[TaskDiagnostic]:
        if context and context.parent_task_ids:
            return [
                TaskDiagnostic(
                    rule_id=self.rule_id,
                    severity=TaskDiagnosticSeverity.ERROR,
                    title=f"Has {len(context.parent_task_ids)} parents",
                    detail="Context-aware diagnostic",
                )
            ]
        return []


class TestDiagnosticEngine:
    def test_empty_engine_returns_empty(self) -> None:
        engine = DiagnosticEngine()
        task = _make_task()
        assert engine.evaluate(task) == []

    def test_register_and_evaluate(self) -> None:
        engine = DiagnosticEngine()
        engine.register(_WarningRule())
        task = _make_task()
        result = engine.evaluate(task)
        assert len(result) == 1
        assert result[0].rule_id == "warn_rule"

    def test_multiple_rules(self) -> None:
        engine = DiagnosticEngine()
        engine.register(_WarningRule())
        engine.register(_ErrorRule())
        task = _make_task()
        result = engine.evaluate(task)
        assert len(result) == 2

    def test_severity_sorting(self) -> None:
        engine = DiagnosticEngine()
        engine.register(_WarningRule())
        engine.register(_CriticalRule())
        engine.register(_ErrorRule())
        task = _make_task()
        result = engine.evaluate(task)
        assert len(result) == 3
        assert result[0].severity == TaskDiagnosticSeverity.CRITICAL
        assert result[1].severity == TaskDiagnosticSeverity.ERROR
        assert result[2].severity == TaskDiagnosticSeverity.WARNING

    def test_exception_swallowed(self) -> None:
        engine = DiagnosticEngine()
        engine.register(_ExplodingRule())
        engine.register(_WarningRule())
        task = _make_task()
        result = engine.evaluate(task)
        assert len(result) == 1
        assert result[0].rule_id == "warn_rule"

    def test_rule_ids_filter(self) -> None:
        engine = DiagnosticEngine()
        engine.register(_WarningRule())
        engine.register(_ErrorRule())
        engine.register(_CriticalRule())
        task = _make_task()

        result = engine.evaluate(task, rule_ids=frozenset({"warn_rule"}))
        assert len(result) == 1
        assert result[0].rule_id == "warn_rule"

    def test_rule_ids_filter_empty_frozenset(self) -> None:
        engine = DiagnosticEngine()
        engine.register(_WarningRule())
        task = _make_task()
        result = engine.evaluate(task, rule_ids=frozenset())
        assert result == []

    def test_rule_ids_filter_none_runs_all(self) -> None:
        engine = DiagnosticEngine()
        engine.register(_WarningRule())
        engine.register(_ErrorRule())
        task = _make_task()
        result = engine.evaluate(task, rule_ids=None)
        assert len(result) == 2

    def test_context_passed_to_rules(self) -> None:
        engine = DiagnosticEngine()
        engine.register(_ContextAwareRule())
        task = _make_task(status=TaskStatus.BACKLOG)

        result_no_ctx = engine.evaluate(task)
        assert result_no_ctx == []

        ctx = DiagnosticContext(parent_task_ids=("p1", "p2"), parent_statuses={"p1": "failed", "p2": "archived"})
        result_with_ctx = engine.evaluate(task, context=ctx)
        assert len(result_with_ctx) == 1
        assert "2 parents" in result_with_ctx[0].title

    def test_rule_ids_property(self) -> None:
        engine = DiagnosticEngine()
        engine.register(_WarningRule())
        engine.register(_ErrorRule())
        assert engine.rule_ids == ["warn_rule", "err_rule"]

    def test_empty_rule_returns_nothing(self) -> None:
        engine = DiagnosticEngine()
        engine.register(_EmptyRule())
        task = _make_task()
        assert engine.evaluate(task) == []

    def test_exploding_rule_does_not_block_others(self) -> None:
        engine = DiagnosticEngine()
        engine.register(_ErrorRule())
        engine.register(_ExplodingRule())
        engine.register(_CriticalRule())
        task = _make_task()
        result = engine.evaluate(task)
        assert len(result) == 2
        rule_ids = [d.rule_id for d in result]
        assert "err_rule" in rule_ids
        assert "crit_rule" in rule_ids
        assert "exploding" not in rule_ids
