"""Tests for DecomposeOutcome, DecomposeChildSpec, and TaskDecomposer Protocol.

Covers the harness-layer contracts for the LLM Decomposer feature:
- DecomposeOutcome dataclass fields, defaults, and frozen invariant
- DecomposeChildSpec fields and defaults
- TaskDecomposer Protocol structural conformance
- DecomposeOutcome fanout=false fields (new_title, new_body, new_assignee)
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from myrm_agent_harness.toolkits.kanban.protocols import (
    DecomposeChildSpec,
    DecomposeOutcome,
    TaskDecomposer,
)
from myrm_agent_harness.toolkits.kanban.types import (
    KanbanTask,
    TaskEventKind,
)


class TestDecomposeChildSpec:
    def test_default_fields(self) -> None:
        spec = DecomposeChildSpec(title="Write tests", body="Cover edge cases")
        assert spec.title == "Write tests"
        assert spec.body == "Cover edge cases"
        assert spec.assignee is None
        assert spec.parent_indices == ()

    def test_with_assignee_and_parents(self) -> None:
        spec = DecomposeChildSpec(
            title="Deploy", body="Deploy to staging",
            assignee="devops-bot", parent_indices=(0, 1),
        )
        assert spec.assignee == "devops-bot"
        assert spec.parent_indices == (0, 1)

    def test_frozen(self) -> None:
        spec = DecomposeChildSpec(title="T", body="B")
        with pytest.raises(FrozenInstanceError):
            spec.title = "X"  # type: ignore[misc]


class TestDecomposeOutcome:
    def test_ok_false_defaults(self) -> None:
        o = DecomposeOutcome(task_id="t1", ok=False, reason="test")
        assert o.task_id == "t1"
        assert not o.ok
        assert o.reason == "test"
        assert o.fanout is False
        assert o.children == ()
        assert o.rationale == ""
        assert o.new_title is None
        assert o.new_body is None
        assert o.new_assignee is None
        assert o.child_ids == ()
        assert o.prompt_tokens is None
        assert o.completion_tokens is None
        assert o.persisted is False

    def test_ok_true_fanout_true(self) -> None:
        child = DecomposeChildSpec(title="C1", body="Body")
        o = DecomposeOutcome(
            task_id="t1", ok=True, fanout=True,
            children=(child,), rationale="test",
            reason="decomposed",
            prompt_tokens=100, completion_tokens=200,
        )
        assert o.ok
        assert o.fanout
        assert len(o.children) == 1
        assert o.children[0].title == "C1"
        assert o.prompt_tokens == 100

    def test_ok_true_fanout_false_with_spec(self) -> None:
        o = DecomposeOutcome(
            task_id="t1", ok=True, fanout=False,
            reason="no_fanout",
            new_title="Refined title",
            new_body="Detailed body",
            new_assignee="research-bot",
            prompt_tokens=50, completion_tokens=80,
        )
        assert o.ok
        assert not o.fanout
        assert o.new_title == "Refined title"
        assert o.new_body == "Detailed body"
        assert o.new_assignee == "research-bot"
        assert o.children == ()

    def test_frozen(self) -> None:
        o = DecomposeOutcome(task_id="t1", ok=True)
        with pytest.raises(FrozenInstanceError):
            o.ok = False  # type: ignore[misc]

    def test_persisted_flag(self) -> None:
        o = DecomposeOutcome(task_id="t1", ok=True, persisted=True)
        assert o.persisted is True


class TestDecomposedEventKind:
    def test_decomposed_is_a_valid_event_kind(self) -> None:
        assert TaskEventKind.DECOMPOSED.value == "decomposed"
        assert TaskEventKind.DECOMPOSED in TaskEventKind


class TestTaskDecomposerProtocol:
    def test_protocol_has_decompose_method(self) -> None:
        assert hasattr(TaskDecomposer, "decompose")

    def test_concrete_class_satisfies_protocol(self) -> None:
        class _FakeDecomposer:
            async def decompose(
                self,
                task: KanbanTask,
                *,
                roster: list[dict[str, str]],
                default_assignee: str,
            ) -> DecomposeOutcome:
                return DecomposeOutcome(task_id=task.task_id, ok=False)

        assert isinstance(_FakeDecomposer(), TaskDecomposer)

    def test_missing_method_not_satisfies(self) -> None:
        class _NoMethod:
            pass

        assert not isinstance(_NoMethod(), TaskDecomposer)
