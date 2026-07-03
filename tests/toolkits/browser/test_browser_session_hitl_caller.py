"""Tests BrowserSession.interact wiring for _hitl_caller_tool audit attribution."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.session.browser_session import BrowserSession
from myrm_agent_harness.toolkits.browser.snapshot.aria_types import RefInfo


def _ref(name: str = "Delete Repository") -> RefInfo:
    return RefInfo(role="button", name=name, nth=None)


@pytest.mark.asyncio
async def test_interact_uses_hitl_caller_tool_when_set() -> None:
    session = object.__new__(BrowserSession)
    session._hitl_caller_tool = "browser_execute_script_tool"
    session._captcha_coordinator = None
    session._ensure_components = AsyncMock()
    session._require_interactor = MagicMock(
        return_value=MagicMock(interact=AsyncMock(return_value="ok"))
    )
    session._tab_controller = MagicMock()
    session._tab_controller.clear_text_snapshot = MagicMock()
    session.get_ref_info = MagicMock(return_value=_ref())

    with patch(
        "myrm_agent_harness.toolkits.browser.tools.semantic_dom_hitl.enforce_semantic_interaction_guard",
        new=AsyncMock(return_value=None),
    ) as guard_mock:
        result = await BrowserSession.interact(session, "click", "e5")

    assert result == "ok"
    guard_mock.assert_awaited_once()
    assert guard_mock.await_args.kwargs["tool_name"] == "browser_execute_script_tool"


@pytest.mark.asyncio
async def test_interact_defaults_to_browser_interact_tool() -> None:
    session = object.__new__(BrowserSession)
    session._hitl_caller_tool = None
    session._captcha_coordinator = None
    session._ensure_components = AsyncMock()
    session._require_interactor = MagicMock(
        return_value=MagicMock(interact=AsyncMock(return_value="ok"))
    )
    session._tab_controller = MagicMock()
    session._tab_controller.clear_text_snapshot = MagicMock()
    session.get_ref_info = MagicMock(return_value=_ref())

    with patch(
        "myrm_agent_harness.toolkits.browser.tools.semantic_dom_hitl.enforce_semantic_interaction_guard",
        new=AsyncMock(return_value="blocked"),
    ) as guard_mock:
        result = await BrowserSession.interact(session, "click", "e5")

    assert result == "blocked"
    assert guard_mock.await_args.kwargs["tool_name"] == "browser_interact_tool"


@pytest.mark.asyncio
async def test_interact_returns_guard_block_without_interactor() -> None:
    session = object.__new__(BrowserSession)
    session._hitl_caller_tool = None
    session._captcha_coordinator = None
    session._ensure_components = AsyncMock()
    interactor = MagicMock(interact=AsyncMock(return_value="should not run"))
    session._require_interactor = MagicMock(return_value=interactor)
    session._tab_controller = MagicMock()
    session._tab_controller.clear_text_snapshot = MagicMock()
    session.get_ref_info = MagicMock(return_value=_ref())

    with patch(
        "myrm_agent_harness.toolkits.browser.tools.semantic_dom_hitl.enforce_semantic_interaction_guard",
        new=AsyncMock(return_value="[BLOCKED] user said no"),
    ):
        result = await BrowserSession.interact(session, "click", "e5")

    assert result == "[BLOCKED] user said no"
    interactor.interact.assert_not_called()

