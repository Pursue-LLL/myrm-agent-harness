"""Unit tests for semantic DOM HITL guards (session.interact + evaluate paths).

Mock LangGraph interrupt only — no real browser or patchright session fixtures.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.snapshot.aria_types import RefInfo
from myrm_agent_harness.toolkits.browser.tools.semantic_dom_hitl import (
    enforce_js_eval_guard,
    enforce_semantic_interaction_guard,
)


@pytest.fixture
def mock_session() -> MagicMock:
    session = MagicMock()
    page = MagicMock()
    page.url = "https://example.com/app"
    session.page = page
    return session


def _ref(role: str = "button", name: str = "Submit") -> RefInfo:
    return RefInfo(role=role, name=name, nth=None)


class TestEnforceSemanticInteractionGuard:
    @pytest.mark.asyncio
    async def test_benign_click_skips_interrupt(self, mock_session: MagicMock) -> None:
        with patch("langgraph.types.interrupt") as mock_interrupt:
            result = await enforce_semantic_interaction_guard(
                session=mock_session,
                tool_name="browser_interact_tool",
                action="click",
                ref="e1",
                ref_info=_ref("button", "Search"),
            )
        assert result is None
        mock_interrupt.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_ref_info_skips_interrupt(self, mock_session: MagicMock) -> None:
        with patch("langgraph.types.interrupt") as mock_interrupt:
            result = await enforce_semantic_interaction_guard(
                session=mock_session,
                tool_name="browser_interact_tool",
                action="click",
                ref="e1",
                ref_info=None,
            )
        assert result is None
        mock_interrupt.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_string_ref_name_skips_interrupt(self, mock_session: MagicMock) -> None:
        bad_ref = MagicMock()
        bad_ref.name = 123
        bad_ref.role = "button"
        with patch("langgraph.types.interrupt") as mock_interrupt:
            result = await enforce_semantic_interaction_guard(
                session=mock_session,
                tool_name="browser_interact_tool",
                action="click",
                ref="e1",
                ref_info=bad_ref,
            )
        assert result is None
        mock_interrupt.assert_not_called()

    @pytest.mark.asyncio
    async def test_high_risk_click_approved(self, mock_session: MagicMock) -> None:
        with patch("langgraph.types.interrupt", return_value={"decision": "approve"}) as mock_interrupt:
            result = await enforce_semantic_interaction_guard(
                session=mock_session,
                tool_name="browser_interact_tool",
                action="click",
                ref="e5",
                ref_info=_ref("button", "Delete Repository"),
            )
        assert result is None
        mock_interrupt.assert_called_once()
        payload = mock_interrupt.call_args[0][0]
        assert payload["action_type"] == "high_risk_dom_action"
        assert payload["tool_name"] == "browser_interact_tool"
        assert payload["page_url"] == "https://example.com/app"
        assert payload["element"] == {
            "role": "button",
            "name": "Delete Repository",
            "ref": "e5",
        }

    @pytest.mark.asyncio
    async def test_high_risk_click_rejected_without_feedback(self, mock_session: MagicMock) -> None:
        with patch("langgraph.types.interrupt", return_value={"decision": "reject"}):
            result = await enforce_semantic_interaction_guard(
                session=mock_session,
                tool_name="browser_interact_tool",
                action="click",
                ref="e5",
                ref_info=_ref("button", "Pay Now"),
            )
        assert result is not None
        assert "[BLOCKED]" in result
        assert "Feedback:" not in result

    @pytest.mark.asyncio
    async def test_high_risk_click_rejected_with_feedback(self, mock_session: MagicMock) -> None:
        with patch(
            "langgraph.types.interrupt",
            return_value={"decision": "reject", "feedback": "Use API instead"},
        ):
            result = await enforce_semantic_interaction_guard(
                session=mock_session,
                tool_name="browser_execute_script_tool",
                action="click",
                ref="e5",
                ref_info=_ref("button", "Pay Now"),
            )
        assert result is not None
        assert "Use API instead" in result

    @pytest.mark.asyncio
    async def test_high_risk_dblclick_approved(self, mock_session: MagicMock) -> None:
        with patch("langgraph.types.interrupt", return_value={"decision": "approve"}) as mock_interrupt:
            result = await enforce_semantic_interaction_guard(
                session=mock_session,
                tool_name="browser_interact_tool",
                action="dblclick",
                ref="e5",
                ref_info=_ref("button", "Delete Repository"),
            )
        assert result is None
        mock_interrupt.assert_called_once()

    @pytest.mark.asyncio
    async def test_string_allow_approves(self, mock_session: MagicMock) -> None:
        with patch("langgraph.types.interrupt", return_value="allow"):
            result = await enforce_js_eval_guard(
                session=mock_session,
                tool_name="browser_manage_tool",
                expression="document.querySelector('button').click()",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_page_url_failure_still_interrupts(self, mock_session: MagicMock) -> None:
        type(mock_session.page).url = property(lambda _self: (_ for _ in ()).throw(RuntimeError("no page")))
        with patch("langgraph.types.interrupt", return_value={"decision": "approve"}) as mock_interrupt:
            result = await enforce_semantic_interaction_guard(
                session=mock_session,
                tool_name="browser_interact_tool",
                action="click",
                ref="e5",
                ref_info=_ref("button", "Delete Repository"),
            )
        assert result is None
        payload = mock_interrupt.call_args[0][0]
        assert payload["page_url"] == ""


class TestEnforceJsEvalGuard:
    @pytest.mark.asyncio
    async def test_read_only_expression_skips_interrupt(self, mock_session: MagicMock) -> None:
        with patch("langgraph.types.interrupt") as mock_interrupt:
            result = await enforce_js_eval_guard(
                session=mock_session,
                tool_name="browser_manage_tool",
                expression="document.title",
            )
        assert result is None
        mock_interrupt.assert_not_called()

    @pytest.mark.asyncio
    async def test_mutating_expression_approved(self, mock_session: MagicMock) -> None:
        expr = "document.querySelector('.pay').click()"
        with patch("langgraph.types.interrupt", return_value={"decision": "approve"}) as mock_interrupt:
            result = await enforce_js_eval_guard(
                session=mock_session,
                tool_name="browser_manage_tool",
                expression=expr,
            )
        assert result is None
        mock_interrupt.assert_called_once()
        payload = mock_interrupt.call_args[0][0]
        assert payload["tool_input"] == {"action": "evaluate", "expression": expr}
        assert payload.get("element") is None

    @pytest.mark.asyncio
    async def test_mutating_expression_string_yes_approved(self, mock_session: MagicMock) -> None:
        with patch("langgraph.types.interrupt", return_value="yes"):
            result = await enforce_js_eval_guard(
                session=mock_session,
                tool_name="browser_manage_tool",
                expression="document.forms[0].submit()",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_mutating_expression_rejected(self, mock_session: MagicMock) -> None:
        with patch("langgraph.types.interrupt", return_value="reject"):
            result = await enforce_js_eval_guard(
                session=mock_session,
                tool_name="browser_manage_tool",
                expression="document.forms[0].submit()",
            )
        assert result is not None
        assert "[BLOCKED]" in result

    @pytest.mark.asyncio
    async def test_invalid_interrupt_response_treated_as_reject(self, mock_session: MagicMock) -> None:
        with patch("langgraph.types.interrupt", return_value=42):
            result = await enforce_js_eval_guard(
                session=mock_session,
                tool_name="browser_manage_tool",
                expression="document.forms[0].submit()",
            )
        assert result is not None
        assert "[BLOCKED]" in result

    @pytest.mark.asyncio
    async def test_string_y_approves(self, mock_session: MagicMock) -> None:
        with patch("langgraph.types.interrupt", return_value="y"):
            result = await enforce_js_eval_guard(
                session=mock_session,
                tool_name="browser_manage_tool",
                expression="document.forms[0].submit()",
            )
        assert result is None
