"""Which approval decisions reach the APPROVAL_CORRECTION hook.

Only a user edit carries a corrected value a hook can react to. A rejection - by a
person or by the system (timeout, fail-closed normalisation) - is never reported to
the hook bus; it stays visible through the audit trail.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.middlewares.approval.middleware import ToolApprovalMiddleware

_FIRE_HOOK = "myrm_agent_harness.agent.hooks.fire_hook"
_TOOL_CALL = {"name": "bash_code_execute_tool", "args": {"command": "rm -r build"}, "id": "tc1"}
_PENDING = [(0, _TOOL_CALL, "shell_exec", "needs approval", None)]


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
@pytest.mark.parametrize(
    "feedback",
    [
        pytest.param(None, id="no-feedback"),
        pytest.param("Use rm -r build/ instead", id="human-reason"),
        pytest.param("Auto-rejected: approval timeout (300s)", id="timeout"),
        pytest.param("Decision count mismatch", id="fail-closed"),
    ],
)
async def test_reject_is_not_reported(feedback: str | None) -> None:
    with patch(_FIRE_HOOK) as fire_hook:
        await ToolApprovalMiddleware._fire_correction_hook(
            [{"type": "reject", "feedback": feedback}], _PENDING, "session-1"
        )

    fire_hook.assert_not_called()


@pytest.mark.asyncio
async def test_only_the_edit_of_a_mixed_batch_is_reported() -> None:
    pending = [
        *_PENDING,
        (1, {**_TOOL_CALL, "id": "tc2", "name": "write_file", "args": {"path": "/tmp/a"}}, "w", "r", None),
    ]
    decisions: list[dict[str, object]] = [
        {"type": "reject", "feedback": "Never write outside the workspace"},
        {"type": "edit", "args": {"path": "/home/user/a"}},
    ]

    with patch(_FIRE_HOOK) as fire_hook:
        await ToolApprovalMiddleware._fire_correction_hook(decisions, pending, "session-1")

    (_event, payload) = fire_hook.call_args.args
    assert [c["tool_name"] for c in payload["corrections"]] == ["write_file"]


@pytest.mark.asyncio
async def test_edit_without_arguments_is_not_reported() -> None:
    with patch(_FIRE_HOOK) as fire_hook:
        await ToolApprovalMiddleware._fire_correction_hook([{"type": "edit"}], _PENDING, "session-1")

    fire_hook.assert_not_called()


@pytest.mark.asyncio
async def test_failing_hook_does_not_break_the_approval_flow() -> None:
    boom = AsyncMock(side_effect=RuntimeError("hook exploded"))
    with patch(_FIRE_HOOK, boom):
        await ToolApprovalMiddleware._fire_correction_hook(
            [{"type": "edit", "args": {"command": "rm -r build/"}}], _PENDING, "session-1"
        )

    boom.assert_awaited_once()


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
