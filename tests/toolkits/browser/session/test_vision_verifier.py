from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage
from patchright.async_api import Page

from myrm_agent_harness.toolkits.browser.session.vision_verifier import VisionVerifier


@pytest.fixture
def mock_page() -> Page:
    page = AsyncMock(spec=Page)
    page.screenshot.return_value = b"fake_new_screenshot_data"
    page.locator.return_value = MagicMock()
    return page


@pytest.fixture
def mock_llm() -> AsyncMock:
    llm = AsyncMock()
    # Return a valid JSON response
    llm.ainvoke.return_value = AIMessage(
        content='SCORE: 5\nREASON: The goal was achieved successfully.'
    )
    return llm


@pytest.mark.asyncio
async def test_vision_verifier_no_llm(mock_page: Page):
    """Test behavior when no LLM is configured (graceful degradation)."""
    verifier = VisionVerifier(llm=None)

    # Mock FastComparator to simulate a visual change so it proceeds to Layer 3
    verifier._comparator.compare = AsyncMock(
        return_value=MagicMock(similarity=0.5)
    )

    success, msg = await verifier.verify_action(
        page=mock_page,
        baseline_screenshot=b"fake_baseline",
        verify_goal="Check if button exists"
    )

    assert success is True
    assert "Vision verification skipped" in msg


@pytest.mark.asyncio
async def test_vision_verifier_no_visual_change(mock_page: Page, mock_llm: AsyncMock):
    """Test Layer 2 (dHash) blocking when screen doesn't change."""
    verifier = VisionVerifier(llm=mock_llm)

    # Mock FastComparator to simulate NO visual change
    verifier._comparator.compare = AsyncMock(
        return_value=MagicMock(similarity=0.995)
    )

    success, msg = await verifier.verify_action(
        page=mock_page,
        baseline_screenshot=b"fake_baseline",
        verify_goal="Check if button exists"
    )

    assert success is False
    assert "screen did not change visually" in msg
    mock_llm.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_vision_verifier_success(mock_page: Page, mock_llm: AsyncMock):
    """Test full 3-layer funnel success."""
    verifier = VisionVerifier(llm=mock_llm)

    # Mock FastComparator to simulate a visual change
    verifier._comparator.compare = AsyncMock(
        return_value=MagicMock(similarity=0.5)
    )

    success, msg = await verifier.verify_action(
        page=mock_page,
        baseline_screenshot=b"fake_baseline",
        verify_goal="Check if button exists"
    )

    assert success is True
    assert "Score 5/5" in msg
    assert "The goal was achieved successfully" in msg
    mock_llm.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_vision_verifier_llm_failure(mock_page: Page, mock_llm: AsyncMock):
    """Test Vision LLM returning a low score."""
    mock_llm.ainvoke.return_value = AIMessage(
        content='SCORE: 3\nREASON: The button is not visible.'
    )
    verifier = VisionVerifier(llm=mock_llm)

    verifier._comparator.compare = AsyncMock(
        return_value=MagicMock(similarity=0.5)
    )

    success, msg = await verifier.verify_action(
        page=mock_page,
        baseline_screenshot=b"fake_baseline",
        verify_goal="Check if button exists"
    )

    assert success is False
    assert "Score 3/5" in msg
    assert "The button is not visible" in msg


@pytest.mark.asyncio
async def test_vision_verifier_invalid_format(mock_page: Page, mock_llm: AsyncMock):
    """Test Vision LLM returning invalid format."""
    mock_llm.ainvoke.return_value = AIMessage(
        content='I cannot see the image'
    )
    verifier = VisionVerifier(llm=mock_llm)

    verifier._comparator.compare = AsyncMock(
        return_value=MagicMock(similarity=0.5)
    )

    success, msg = await verifier.verify_action(
        page=mock_page,
        baseline_screenshot=b"fake_baseline",
        verify_goal="Check if button exists"
    )

    assert success is False
    assert "Score 1/5" in msg
