"""Tests execute_script _hitl_caller_tool lifecycle (set during run, reset in finally)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.tools.execute_script import create_execute_script_tool


@pytest.fixture
def mock_session() -> MagicMock:
    session = MagicMock()
    session._hitl_caller_tool = None
    session.get_all_refs.return_value = {}
    session.notify_progress = AsyncMock()
    session.list_downloads.return_value = []
    return session


@pytest.mark.asyncio
async def test_hitl_caller_set_during_execution(mock_session: MagicMock) -> None:
    tool = create_execute_script_tool(mock_session)
    seen: list[str | None] = []

    async def _fake_wait(coro, timeout):  # noqa: ANN001
        async def _run_and_capture():
            seen.append(mock_session._hitl_caller_tool)
            return await coro

        return await _run_and_capture()

    with patch("asyncio.wait_for", side_effect=_fake_wait):
        await tool.ainvoke({"script": "pass"})

    assert seen == ["browser_execute_script_tool"]
    assert mock_session._hitl_caller_tool is None


@pytest.mark.asyncio
async def test_hitl_caller_reset_after_timeout(mock_session: MagicMock) -> None:
    tool = create_execute_script_tool(mock_session)

    with patch("asyncio.wait_for", side_effect=TimeoutError) as wait_mock:
        result = await tool.ainvoke({"script": "pass"})
        if wait_mock.call_args is not None:
            coro = wait_mock.call_args[0][0]
            coro.close()

    assert "timed out" in result.lower()
    assert mock_session._hitl_caller_tool is None


@pytest.mark.asyncio
async def test_hitl_caller_reset_after_runtime_error(mock_session: MagicMock) -> None:
    tool = create_execute_script_tool(mock_session)

    async def _fake_wait(coro, timeout):  # noqa: ANN001
        return await coro

    with patch("asyncio.wait_for", side_effect=_fake_wait):
        result = await tool.ainvoke({"script": "raise RuntimeError('boom')"})

    assert "Runtime exception" in result
    assert mock_session._hitl_caller_tool is None
