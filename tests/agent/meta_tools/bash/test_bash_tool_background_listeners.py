"""Unit tests for bash_tool_background_listeners."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.bash.bash_tool_background_listeners import (
    build_background_listeners,
    classify_background_exit,
)


class _FakeInfo:
    def __init__(
        self,
        *,
        pid: int = 1,
        command: str = "echo hi",
        status: str = "exited",
        exit_code: int | None = 0,
    ) -> None:
        self.pid = pid
        self.command = command
        self.status = status
        self.exit_code = exit_code


@pytest.mark.parametrize(
    ("exit_code", "status", "expected"),
    [
        (0, "exited", None),
        (None, "exited", None),
        (137, "exited", "oom_killed"),
        (139, "exited", "segfault"),
        (143, "exited", "signal_terminated"),
        (-9, "exited", "signal_terminated"),
        (2, "exited", "nonzero_exit"),
        (130, "killed", None),
    ],
)
def test_classify_background_exit_branches(
    exit_code: int | None,
    status: str,
    expected: str | None,
) -> None:
    info = _FakeInfo(status=status, exit_code=exit_code)
    assert classify_background_exit(info) == expected  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_on_finish_emits_warn_level_for_nonzero_exit() -> None:
    config: dict[str, object] = {}
    info = _FakeInfo(pid=3, status="exited", exit_code=2)
    dispatch = AsyncMock()

    with patch(
        "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
        dispatch,
    ):
        finish, _progress = build_background_listeners(session_id="sess", config=config)  # type: ignore[arg-type]
        await finish(info)  # type: ignore[arg-type]

    envelope = dispatch.await_args.args[1]
    assert envelope["level"] == "warn"
    assert envelope["progress"] == 100


@pytest.mark.asyncio
async def test_on_finish_emits_alert_for_oom() -> None:
    config: dict[str, object] = {}
    info = _FakeInfo(pid=4, status="exited", exit_code=137)
    dispatch = AsyncMock()

    with patch(
        "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
        dispatch,
    ):
        finish, _progress = build_background_listeners(session_id="sess", config=config)  # type: ignore[arg-type]
        await finish(info)  # type: ignore[arg-type]

    envelope = dispatch.await_args.args[1]
    assert envelope["level"] == "alert"
    assert envelope["error_category"] == "oom_killed"


@pytest.mark.asyncio
async def test_on_finish_swallows_finish_handler_errors() -> None:
    config: dict[str, object] = {}
    info = _FakeInfo(pid=5, status="exited", exit_code=0)
    handler = MagicMock()
    handler.on_background_job_finish = AsyncMock(side_effect=RuntimeError("db down"))

    with (
        patch(
            "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
            AsyncMock(),
        ),
        patch(
            "myrm_agent_harness.utils.runtime.background_job_finish_registry.get_global_background_job_finish_handler",
            return_value=handler,
        ),
    ):
        finish, _progress = build_background_listeners(session_id="sess", config=config)  # type: ignore[arg-type]
        await finish(info)  # type: ignore[arg-type]

    handler.on_background_job_finish.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_finish_killed_is_silent() -> None:
    config: dict[str, object] = {}
    info = _FakeInfo(pid=6, status="killed", exit_code=None)
    dispatch = AsyncMock()

    with patch(
        "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
        dispatch,
    ):
        finish, _progress = build_background_listeners(session_id="sess", config=config)  # type: ignore[arg-type]
        await finish(info)  # type: ignore[arg-type]

    dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_progress_dispatches_payload_fields() -> None:
    config: dict[str, object] = {}
    info = _FakeInfo(pid=8, command="build")
    dispatch = AsyncMock()

    with patch(
        "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
        dispatch,
    ):
        _finish, progress = build_background_listeners(session_id="sess", config=config)  # type: ignore[arg-type]
        await progress(info, {"message": "50%", "progress": 50, "step_index": 1, "total_steps": 2})  # type: ignore[arg-type]

    envelope = dispatch.await_args.args[1]
    assert envelope["message"] == "50%"
    assert envelope["progress"] == 50
    assert envelope["step_index"] == 1
    assert envelope["total_steps"] == 2


def test_classify_background_exit_none_code_non_success() -> None:
    info = _FakeInfo(status="running", exit_code=None)
    assert classify_background_exit(info) is None  # type: ignore[arg-type]
