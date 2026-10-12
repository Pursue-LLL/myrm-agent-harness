"""Which approval decisions reach correction learning.

Only a user edit carries a corrected value worth remembering. A rejection - by a
person or by the system (timeout, fail-closed normalisation) - is never reported to
the hook bus and never becomes a stored rule.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from unittest.mock import patch

import pytest

from myrm_agent_harness.agent.middlewares.approval.correction_learning import CorrectionLearningHook
from myrm_agent_harness.agent.middlewares.approval.middleware import ToolApprovalMiddleware
from myrm_agent_harness.core.hooks.types import HookResult

_FIRE_HOOK = "myrm_agent_harness.agent.hooks.fire_hook"
_MEMORY_MANAGER = "myrm_agent_harness.agent.skill_agent.context.get_memory_manager"
_TOOL_CALL = {"name": "bash_code_execute_tool", "args": {"command": "rm -r build"}, "id": "tc1"}
_PENDING = [(0, _TOOL_CALL, "shell_exec", "needs approval", None)]


def _learning_fire_hook(hook: CorrectionLearningHook) -> Callable[..., Awaitable[object]]:
    """A ``fire_hook`` stand-in that runs the real correction-learning handler."""

    class _Outcome:
        def __init__(self, results: list[HookResult]) -> None:
            self.results = results

    async def fire(event: object, payload: dict[str, object]) -> _Outcome:
        return _Outcome([await hook.on_approval_correction(str(event), payload)])

    return fire


async def _learn(
    decisions: list[dict[str, object]], pending: list[tuple[object, ...]] = _PENDING
) -> CorrectionLearningHook:
    hook = CorrectionLearningHook()
    with patch(_FIRE_HOOK, _learning_fire_hook(hook)), patch(_MEMORY_MANAGER, return_value=None):
        await ToolApprovalMiddleware._fire_correction_hook(decisions, pending, "session-1")
    return hook


@pytest.mark.asyncio
async def test_edit_is_reported_with_both_argument_sets() -> None:
    with patch(_FIRE_HOOK) as fire_hook:
        await ToolApprovalMiddleware._fire_correction_hook(
            [{"type": "edit", "args": {"command": "rm -r build/"}}], _PENDING, "session-1"
        )

    (_event, payload) = fire_hook.call_args.args
    assert payload["session_id"] == "session-1"
    assert payload["corrections"] == (
        {
            "tool_name": "bash_code_execute_tool",
            "original_args": {"command": "rm -r build"},
            "edited_args": {"command": "rm -r build/"},
        },
    )


@pytest.mark.asyncio
async def test_edit_is_learned_as_a_tool_scoped_rule() -> None:
    hook = await _learn([{"type": "edit", "args": {"command": "rm -r build/"}}])

    (rule,) = hook.pending_rules
    assert rule.tool_name == "bash_code_execute_tool"
    assert "rm -r build/" in rule.content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "feedback",
    [
        pytest.param(None, id="no-feedback"),
        pytest.param("Use rm -r build/ instead", id="human-reason"),
        pytest.param("Auto-rejected: approval timeout (300s)", id="timeout"),
        pytest.param("Decision count mismatch", id="fail-closed"),
    ],
)
async def test_reject_is_not_reported_nor_learned(feedback: str | None) -> None:
    with patch(_FIRE_HOOK) as fire_hook:
        await ToolApprovalMiddleware._fire_correction_hook(
            [{"type": "reject", "feedback": feedback}], _PENDING, "session-1"
        )
    fire_hook.assert_not_called()

    hook = await _learn([{"type": "reject", "feedback": feedback}])
    assert hook.pending_rules == []
    assert hook.pending_preferences == []


@pytest.mark.asyncio
async def test_only_the_edit_of_a_mixed_batch_is_learned() -> None:
    pending = [
        *_PENDING,
        (1, {**_TOOL_CALL, "id": "tc2", "name": "write_file", "args": {"path": "/tmp/a"}}, "w", "r", None),
    ]
    decisions: list[dict[str, object]] = [
        {"type": "reject", "feedback": "Never write outside the workspace"},
        {"type": "edit", "args": {"path": "/home/user/a"}},
    ]

    hook = await _learn(decisions, pending)

    (preference,) = hook.pending_preferences
    assert "write_file" in preference.content
    assert hook.pending_rules == []


@pytest.mark.asyncio
async def test_edit_without_arguments_is_not_reported() -> None:
    with patch(_FIRE_HOOK) as fire_hook:
        await ToolApprovalMiddleware._fire_correction_hook([{"type": "edit"}], _PENDING, "session-1")

    fire_hook.assert_not_called()


@pytest.mark.parametrize(
    "batch_response",
    [
        pytest.param("not a dict", id="invalid-response"),
        pytest.param({"decisions": [{"type": "approve"}]}, id="count-mismatch"),
    ],
)
def test_malformed_batch_response_rejects_every_tool(batch_response: object) -> None:
    decisions = ToolApprovalMiddleware._normalize_batch_decisions(batch_response, expected_count=2, phase="primary")

    assert [d["type"] for d in decisions] == ["reject", "reject"]
