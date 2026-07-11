"""Tests _require_privileged_api_approval HITL flow in execute_script."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.tools.execute_script import (
    _require_privileged_api_approval,
)


@pytest.fixture
def mock_session() -> MagicMock:
    session = MagicMock()
    session._hitl_caller_tool = None
    session.get_all_refs.return_value = {}
    session.notify_progress = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_approval_returns_none_on_dict_approve(mock_session: MagicMock) -> None:
    with (
        patch("langgraph.types.interrupt", return_value={"decision": "approve"}) as mock_interrupt,
        patch("myrm_agent_harness.core.security.audit.record_decision"),
    ):
        result = await _require_privileged_api_approval(
            mock_session, [".request.get()"], "await page.request.get('http://x.com')"
        )
    assert result is None
    mock_interrupt.assert_called_once()


@pytest.mark.asyncio
async def test_approval_returns_none_on_string_approve(mock_session: MagicMock) -> None:
    with (
        patch("langgraph.types.interrupt", return_value="yes"),
        patch("myrm_agent_harness.core.security.audit.record_decision"),
    ):
        result = await _require_privileged_api_approval(
            mock_session, [".evaluate"], "await page.evaluate('1+1')"
        )
    assert result is None


@pytest.mark.asyncio
async def test_approval_returns_blocked_on_reject(mock_session: MagicMock) -> None:
    with (
        patch("langgraph.types.interrupt", return_value={"decision": "reject", "feedback": "Too dangerous"}),
        patch("myrm_agent_harness.core.security.audit.record_decision"),
    ):
        result = await _require_privileged_api_approval(
            mock_session, [".request.post()"], "await page.request.post('http://evil.com')"
        )
    assert result is not None
    assert "[BLOCKED]" in result
    assert "Too dangerous" in result


@pytest.mark.asyncio
async def test_approval_returns_blocked_on_unknown_response(mock_session: MagicMock) -> None:
    with (
        patch("langgraph.types.interrupt", return_value="no"),
        patch("myrm_agent_harness.core.security.audit.record_decision"),
    ):
        result = await _require_privileged_api_approval(
            mock_session, [".context"], "ctx = page.context"
        )
    assert result is not None
    assert "[BLOCKED]" in result


@pytest.mark.asyncio
async def test_approval_records_audit_decisions(mock_session: MagicMock) -> None:
    with (
        patch("langgraph.types.interrupt", return_value={"decision": "approve"}),
        patch("myrm_agent_harness.core.security.audit.record_decision") as mock_record,
    ):
        await _require_privileged_api_approval(
            mock_session, [".request.get()"], "script"
        )
    assert mock_record.call_count == 2
    assert mock_record.call_args_list[0][0][1] == "ASK"
    assert mock_record.call_args_list[1][0][1] == "USER_APPROVED"


@pytest.mark.asyncio
async def test_approval_records_reject_audit(mock_session: MagicMock) -> None:
    with (
        patch("langgraph.types.interrupt", return_value={"decision": "reject"}),
        patch("myrm_agent_harness.core.security.audit.record_decision") as mock_record,
    ):
        await _require_privileged_api_approval(
            mock_session, [".evaluate"], "script"
        )
    assert mock_record.call_count == 2
    assert mock_record.call_args_list[1][0][1] == "USER_REJECTED"


@pytest.mark.asyncio
async def test_approval_script_preview_truncated(mock_session: MagicMock) -> None:
    long_script = "x" * 1000
    with (
        patch("langgraph.types.interrupt", return_value={"decision": "approve"}) as mock_interrupt,
        patch("myrm_agent_harness.core.security.audit.record_decision"),
    ):
        await _require_privileged_api_approval(
            mock_session, [".request.get()"], long_script
        )
    payload = mock_interrupt.call_args[0][0]
    assert len(payload["script_preview"]) == 500
