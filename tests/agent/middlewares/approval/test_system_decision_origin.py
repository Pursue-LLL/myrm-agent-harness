"""System-made approval decisions must not be learned as user feedback.

An approval timeout, a malformed resume payload and a decision-count mismatch all
produce a ``reject`` without any human involved. Those decisions carry
``origin="system"`` and are skipped by correction learning, while a person's own
reject or edit is still learned.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from unittest.mock import patch

import pytest

from myrm_agent_harness.agent.middlewares.approval.correction_learning import CorrectionLearningHook
from myrm_agent_harness.agent.middlewares.approval.middleware import ToolApprovalMiddleware
from myrm_agent_harness.agent.middlewares.approval.scheduler import ApprovalTimeoutScheduler
from myrm_agent_harness.core.hooks.types import HookResult

_FIRE_HOOK = "myrm_agent_harness.agent.hooks.fire_hook"
_MEMORY_MANAGER = "myrm_agent_harness.agent.skill_agent.context.get_memory_manager"
_TOOL_CALL = {"name": "bash_code_execute_tool", "args": {"command": "rm -r build"}, "id": "tc1"}
_PENDING = [(0, _TOOL_CALL, "shell_exec", "needs approval", None)]


@pytest.fixture(autouse=True)
def _reset_scheduler_singleton() -> None:
    ApprovalTimeoutScheduler._instance = None


def _learning_fire_hook(hook: CorrectionLearningHook) -> Callable[..., Awaitable[object]]:
    """A ``fire_hook`` stand-in that runs the real correction-learning handler."""

    class _Outcome:
        def __init__(self, results: list[HookResult]) -> None:
            self.results = results

    async def fire(event: object, payload: dict[str, object]) -> _Outcome:
        return _Outcome([await hook.on_approval_correction(str(event), payload)])

    return fire


async def _learn(decisions: list[dict[str, object]]) -> CorrectionLearningHook:
    hook = CorrectionLearningHook()
    with patch(_FIRE_HOOK, _learning_fire_hook(hook)), patch(_MEMORY_MANAGER, return_value=None):
        await ToolApprovalMiddleware._fire_correction_hook(decisions, _PENDING, "session-1")
    return hook


@pytest.mark.asyncio
@pytest.mark.parametrize(("behavior", "decision"), [("deny", "reject"), ("allow", "approve")])
async def test_timeout_resume_value_is_system_origin(behavior: str, decision: str) -> None:
    received: list[dict[str, object]] = []

    async def callback(resume_value: dict[str, object]) -> None:
        received.append(resume_value)

    ApprovalTimeoutScheduler.get().schedule(
        "origin-key", timeout_seconds=0.05, behavior=behavior, resume_callback=callback
    )
    await asyncio.sleep(0.15)

    assert received[0]["decision"] == decision
    assert received[0]["origin"] == "system"


def test_global_decision_carries_origin_to_every_tool() -> None:
    decisions = ToolApprovalMiddleware._normalize_batch_decisions(
        {"decision": "reject", "feedback": "Auto-rejected: approval timeout (300s)", "origin": "system"},
        expected_count=2,
        phase="primary",
    )

    assert [d["origin"] for d in decisions] == ["system", "system"]


def test_global_decision_without_origin_has_none() -> None:
    decisions = ToolApprovalMiddleware._normalize_batch_decisions(
        {"decision": "reject", "feedback": "too risky"},
        expected_count=1,
        phase="primary",
    )

    assert "origin" not in decisions[0]


@pytest.mark.parametrize(
    "batch_response",
    [
        pytest.param("not a dict", id="invalid-response"),
        pytest.param({"decisions": [{"type": "approve"}]}, id="count-mismatch"),
    ],
)
def test_fail_closed_rejects_are_system_origin(batch_response: object) -> None:
    decisions = ToolApprovalMiddleware._normalize_batch_decisions(batch_response, expected_count=2, phase="primary")

    assert [d["type"] for d in decisions] == ["reject", "reject"]
    assert all(d["origin"] == "system" for d in decisions)


@pytest.mark.asyncio
async def test_system_reject_is_not_learned() -> None:
    hook = await _learn([{"type": "reject", "feedback": "Auto-rejected: approval timeout (300s)", "origin": "system"}])

    assert hook.pending_rules == []
    assert hook.pending_preferences == []


@pytest.mark.asyncio
async def test_system_reject_does_not_reach_the_hook_bus() -> None:
    with patch(_FIRE_HOOK) as fire_hook:
        await ToolApprovalMiddleware._fire_correction_hook(
            [{"type": "reject", "feedback": "Decision count mismatch", "origin": "system"}], _PENDING, "session-1"
        )

    fire_hook.assert_not_called()


@pytest.mark.asyncio
async def test_human_reject_is_still_learned() -> None:
    hook = CorrectionLearningHook()
    with patch(_FIRE_HOOK, _learning_fire_hook(hook)), patch(_MEMORY_MANAGER, return_value=None):
        await ToolApprovalMiddleware._fire_correction_hook(
            [{"type": "reject", "feedback": "Use rm -r build/ instead"}], _PENDING, "session-1"
        )

    (rule,) = hook.pending_rules
    assert rule.tool_name == "bash_code_execute_tool"
    assert "Use rm -r build/ instead" in rule.action


@pytest.mark.asyncio
async def test_human_edit_is_still_learned() -> None:
    hook = await _learn([{"type": "edit", "args": {"command": "rm -r build/"}}])

    (rule,) = hook.pending_rules
    assert "rm -r build/" in rule.content


@pytest.mark.asyncio
async def test_system_decision_in_a_mixed_batch_is_skipped_individually() -> None:
    pending = [
        *_PENDING,
        (1, {**_TOOL_CALL, "id": "tc2", "name": "write_file", "args": {"path": "/tmp/a"}}, "w", "r", None),
    ]
    hook = CorrectionLearningHook()
    decisions: list[dict[str, object]] = [
        {"type": "reject", "feedback": "Decision count mismatch", "origin": "system"},
        {"type": "reject", "feedback": "Never write outside the workspace"},
    ]
    with patch(_FIRE_HOOK, _learning_fire_hook(hook)), patch(_MEMORY_MANAGER, return_value=None):
        await ToolApprovalMiddleware._fire_correction_hook(decisions, pending, "session-1")

    (rule,) = hook.pending_rules
    assert rule.tool_name == "write_file"


@pytest.mark.asyncio
async def test_reject_without_feedback_does_not_learn_the_word_none() -> None:
    """A UI reject carries ``feedback=None``; it must not be stored as the text "None"."""
    hook = await _learn([{"type": "reject", "feedback": None}])

    (rule,) = hook.pending_rules
    assert "None" not in rule.action
