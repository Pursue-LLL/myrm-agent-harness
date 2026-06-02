"""Unit tests for ARIA tree acquisition."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.snapshot.aria_acquisition import (
    get_aria_tree,
)


@pytest.fixture
def mock_locator():
    locator = MagicMock()
    locator.page = MagicMock()
    locator.page.evaluate = AsyncMock()
    locator.aria_snapshot = AsyncMock()
    locator.evaluate = AsyncMock()
    return locator

@pytest.mark.asyncio
async def test_get_aria_tree_fast_path(mock_locator):
    """Test fast path routing when max_depth is None."""
    mock_locator.page.evaluate.return_value = ["secret123"]
    mock_locator.aria_snapshot.return_value = '- textbox "Password": secret123\n- button "Submit"'

    result = await get_aria_tree(mock_locator, max_depth=None)

    assert "secret123" not in result
    assert '[PASSWORD HIDDEN]' in result
    assert '- button "Submit"' in result
    mock_locator.aria_snapshot.assert_called_once()

@pytest.mark.asyncio
async def test_get_aria_tree_fast_path_no_passwords(mock_locator):
    """Test fast path when no passwords exist."""
    mock_locator.page.evaluate.return_value = []
    mock_locator.aria_snapshot.return_value = '- textbox "Username": user1\n- button "Submit"'

    result = await get_aria_tree(mock_locator, max_depth=None)

    assert "user1" in result
    assert '[PASSWORD HIDDEN]' not in result
    mock_locator.aria_snapshot.assert_called_once()

@pytest.mark.asyncio
async def test_get_aria_tree_custom_path(mock_locator):
    """Test custom path routing when max_depth is set."""
    mock_locator.evaluate.return_value = '- textbox "Password"\n- button "Submit"'

    result = await get_aria_tree(mock_locator, max_depth=5)

    assert result == '- textbox "Password"\n- button "Submit"'
    mock_locator.evaluate.assert_called_once()

@pytest.mark.asyncio
async def test_get_aria_tree_invalid_depth(mock_locator):
    """Test invalid max_depth values."""
    with pytest.raises(ValueError, match="must be int or None"):
        await get_aria_tree(mock_locator, max_depth="5")

    with pytest.raises(ValueError, match="must be >= 0"):
        await get_aria_tree(mock_locator, max_depth=-1)

@pytest.mark.asyncio
async def test_get_aria_tree_depth_fallback(mock_locator):
    """Test max_depth > 100 falls back to fast path."""
    mock_locator.page.evaluate.return_value = []
    mock_locator.aria_snapshot.return_value = '- root'

    result = await get_aria_tree(mock_locator, max_depth=150)

    assert result == '- root'
    mock_locator.aria_snapshot.assert_called_once()
    mock_locator.evaluate.assert_not_called()

@pytest.mark.asyncio
async def test_get_aria_tree_custom_path_timeout_fallback(mock_locator):
    """Test custom path timeout falls back to fast path."""
    import asyncio

    async def slow_evaluate(*args, **kwargs):
        await asyncio.sleep(5.0)
        return ""

    mock_locator.evaluate.side_effect = slow_evaluate
    mock_locator.page.evaluate.return_value = []
    mock_locator.aria_snapshot.return_value = '- fallback'

    result = await get_aria_tree(mock_locator, max_depth=5)

    assert result == '- fallback'
    mock_locator.aria_snapshot.assert_called_once()

@pytest.mark.asyncio
async def test_get_aria_tree_custom_path_error_fallback(mock_locator):
    """Test custom path error falls back to fast path."""
    mock_locator.evaluate.side_effect = Exception("JS Error")
    mock_locator.page.evaluate.return_value = []
    mock_locator.aria_snapshot.return_value = '- fallback'

    result = await get_aria_tree(mock_locator, max_depth=5)

    assert result == '- fallback'
    mock_locator.aria_snapshot.assert_called_once()
