"""Unit tests for browser_interact navigation post-action guard in batch mode."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from myrm_agent_harness.toolkits.browser.tools.interact import InteractStep, create_interact_tool


@pytest.fixture
def mock_session() -> MagicMock:
    session = MagicMock()
    mock_page = MagicMock()
    mock_page.url = "https://example.com/form"
    session.get_active_page.return_value = mock_page
    session.download_enabled = False
    session.list_downloads.return_value = []
    session.interact = AsyncMock(return_value="Action executed successfully")
    return session


@pytest.mark.asyncio
async def test_batch_interact_executes_all_when_no_navigation(mock_session: MagicMock) -> None:
    with patch("myrm_agent_harness.core.security.credential_vault.get_global_credential_vault") as mock_vault:
        mock_vault.return_value.list_labels.return_value = []
        tool = create_interact_tool(mock_session)

        steps = [
            InteractStep(action="click", ref="e1"),
            InteractStep(action="fill", ref="e2", text="hello"),
            InteractStep(action="click", ref="e3"),
        ]

        result = await tool.ainvoke({"steps": steps})

        assert "Step 1 (click e1): Action executed successfully" in result
        assert "Step 2 (fill e2): Action executed successfully" in result
        assert "Step 3 (click e3): Action executed successfully" in result
        assert "[NAVIGATION_HALTED" not in result
        assert mock_session.interact.await_count == 3


@pytest.mark.asyncio
async def test_batch_interact_halts_on_hard_navigation(mock_session: MagicMock) -> None:
    mock_page = mock_session.get_active_page()

    # Step 1 executes on /form, then page.url changes to /success
    async def simulate_step_1_nav(*args, **kwargs):
        mock_page.url = "https://example.com/success"
        return "Clicked submit"

    mock_session.interact.side_effect = simulate_step_1_nav

    with patch("myrm_agent_harness.core.security.credential_vault.get_global_credential_vault") as mock_vault:
        mock_vault.return_value.list_labels.return_value = []
        tool = create_interact_tool(mock_session)

        steps = [
            InteractStep(action="click", ref="e1"),
            InteractStep(action="fill", ref="e2", text="unreached_text"),
            InteractStep(action="click", ref="e3"),
        ]

        result = await tool.ainvoke({"steps": steps})

        assert "Step 1 (click e1): Clicked submit" in result
        assert "[NAVIGATION_HALTED: Step 1 triggered navigation to 'https://example.com/success'." in result
        assert "Remaining 2 steps halted to prevent stale element execution." in result
        assert "Step 2" not in result
        assert "Step 3" not in result
        assert mock_session.interact.await_count == 1


@pytest.mark.asyncio
async def test_batch_interact_allows_spa_query_change(mock_session: MagicMock) -> None:
    mock_page = mock_session.get_active_page()

    # Step 1 updates query param (SPA soft routing)
    async def simulate_spa_filter(*args, **kwargs):
        mock_page.url = "https://example.com/form?tab=active"
        return "Clicked tab"

    mock_session.interact.side_effect = [
        "Clicked tab",
        "Filled filter",
    ]

    # Simulating url mutation after step 1
    call_count = 0

    async def side_effect_mock(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            mock_page.url = "https://example.com/form?tab=active"
            return "Clicked tab"
        return "Filled input"

    mock_session.interact.side_effect = side_effect_mock

    with patch("myrm_agent_harness.core.security.credential_vault.get_global_credential_vault") as mock_vault:
        mock_vault.return_value.list_labels.return_value = []
        tool = create_interact_tool(mock_session)

        steps = [
            InteractStep(action="click", ref="e1"),
            InteractStep(action="fill", ref="e2", text="some query"),
        ]

        result = await tool.ainvoke({"steps": steps})

        assert "Step 1 (click e1): Clicked tab" in result
        assert "Step 2 (fill e2): Filled input" in result
        assert "[NAVIGATION_HALTED" not in result
        assert mock_session.interact.await_count == 2
