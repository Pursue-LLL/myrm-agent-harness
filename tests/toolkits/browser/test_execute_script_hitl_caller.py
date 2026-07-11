"""Tests execute_script tool lifecycle, error paths, and privileged API blocking."""

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


@pytest.mark.asyncio
async def test_syntax_error_returns_message(mock_session: MagicMock) -> None:
    tool = create_execute_script_tool(mock_session)
    result = await tool.ainvoke({"script": "def foo(:"})
    assert "SyntaxError" in result


@pytest.mark.asyncio
async def test_successful_print_output(mock_session: MagicMock) -> None:
    tool = create_execute_script_tool(mock_session)

    async def _fake_wait(coro, timeout):  # noqa: ANN001
        return await coro

    with patch("asyncio.wait_for", side_effect=_fake_wait):
        result = await tool.ainvoke({"script": "print('hello from script')"})

    assert "hello from script" in result


@pytest.mark.asyncio
async def test_no_output_returns_success_message(mock_session: MagicMock) -> None:
    tool = create_execute_script_tool(mock_session)

    async def _fake_wait(coro, timeout):  # noqa: ANN001
        return await coro

    with patch("asyncio.wait_for", side_effect=_fake_wait):
        result = await tool.ainvoke({"script": "x = 1"})

    assert "Script executed successfully" in result


@pytest.mark.asyncio
async def test_privileged_api_blocked_when_rejected(mock_session: MagicMock) -> None:
    tool = create_execute_script_tool(mock_session)

    with (
        patch("langgraph.types.interrupt", return_value={"decision": "reject"}),
        patch("myrm_agent_harness.core.security.audit.record_decision"),
    ):
        result = await tool.ainvoke({"script": "await page.request.get('http://evil.com')"})

    assert "[BLOCKED]" in result


@pytest.mark.asyncio
async def test_privileged_api_allowed_when_approved(mock_session: MagicMock) -> None:
    tool = create_execute_script_tool(mock_session)

    async def _fake_wait(coro, timeout):  # noqa: ANN001
        return await coro

    with (
        patch("langgraph.types.interrupt", return_value={"decision": "approve"}),
        patch("myrm_agent_harness.core.security.audit.record_decision"),
        patch("asyncio.wait_for", side_effect=_fake_wait),
    ):
        result = await tool.ainvoke({"script": "print('approved')"})

    assert "approved" in result


@pytest.mark.asyncio
async def test_getattr_blocked_in_runtime(mock_session: MagicMock) -> None:
    tool = create_execute_script_tool(mock_session)

    async def _fake_wait(coro, timeout):  # noqa: ANN001
        return await coro

    with patch("asyncio.wait_for", side_effect=_fake_wait):
        result = await tool.ainvoke({"script": "x = getattr(session, '_tab_controller')"})

    assert "Runtime exception" in result or "NameError" in result.lower() or "name" in result.lower()


@pytest.mark.asyncio
async def test_verify_goal_with_mock_page(mock_session: MagicMock) -> None:
    mock_page = MagicMock()
    mock_page.locator.return_value = MagicMock()
    mock_page.screenshot = AsyncMock(return_value=b"fake_png")
    mock_session._tab_controller.get_active_page.return_value = mock_page
    mock_session._vision_verifier = MagicMock()
    mock_session._vision_verifier.verify_action = AsyncMock(return_value=(True, "[PASS] Goal met"))

    tool = create_execute_script_tool(mock_session)

    async def _fake_wait(coro, timeout):  # noqa: ANN001
        return await coro

    with patch("asyncio.wait_for", side_effect=_fake_wait):
        result = await tool.ainvoke({"script": "print('done')", "verify_goal": "Page loaded"})

    assert "[PASS] Goal met" in result


@pytest.mark.asyncio
async def test_verify_goal_screenshot_failure_graceful(mock_session: MagicMock) -> None:
    mock_session._tab_controller.get_active_page.side_effect = Exception("No page")

    tool = create_execute_script_tool(mock_session)

    async def _fake_wait(coro, timeout):  # noqa: ANN001
        return await coro

    with patch("asyncio.wait_for", side_effect=_fake_wait):
        result = await tool.ainvoke({"script": "print('ok')", "verify_goal": "Something"})

    assert "ok" in result
