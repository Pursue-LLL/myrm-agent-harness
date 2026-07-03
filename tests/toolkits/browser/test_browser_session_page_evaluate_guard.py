"""Tests BrowserSessionPageMixin.evaluate wiring for enforce_js_eval_guard."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.session.browser_session_page_mixin import (
    BrowserSessionPageMixin,
)


class _EvalSession(BrowserSessionPageMixin):
    async def _ensure_components(self) -> None:
        return None


@pytest.mark.asyncio
async def test_evaluate_returns_guard_block_without_page_evaluate() -> None:
    session = _EvalSession()
    session._tab_controller = MagicMock()

    with patch(
        "myrm_agent_harness.toolkits.browser.tools.semantic_dom_hitl.enforce_js_eval_guard",
        new=AsyncMock(return_value="[BLOCKED] rejected"),
    ) as guard_mock:
        result = await session.evaluate("document.forms[0].submit()")

    assert result == "[BLOCKED] rejected"
    guard_mock.assert_awaited_once_with(
        session=session,
        tool_name="browser_manage_tool",
        expression="document.forms[0].submit()",
    )
    session._tab_controller.get_active_page.assert_not_called()


@pytest.mark.asyncio
async def test_evaluate_runs_page_evaluate_when_guard_passes() -> None:
    session = _EvalSession()
    page = MagicMock()
    page.evaluate = AsyncMock(return_value=42)
    session._tab_controller = MagicMock()
    session._tab_controller.get_active_page.return_value = page

    with patch(
        "myrm_agent_harness.toolkits.browser.tools.semantic_dom_hitl.enforce_js_eval_guard",
        new=AsyncMock(return_value=None),
    ):
        result = await session.evaluate("document.title")

    assert result == "42"
    page.evaluate.assert_awaited_once_with("document.title")
