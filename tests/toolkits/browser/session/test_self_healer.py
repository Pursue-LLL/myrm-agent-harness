import time
from unittest.mock import AsyncMock

import pytest
from patchright.async_api import Locator, Page

from myrm_agent_harness.toolkits.browser.snapshot.aria_types import BBox, RefInfo
from myrm_agent_harness.toolkits.browser.snapshot.self_healer import SelfHealer


@pytest.mark.asyncio
async def test_self_healer_performance():
    page = AsyncMock(spec=Page)
    ref_info = RefInfo(role="button", name="Submit", nth=0, bbox=BBox(x=10, y=10, width=100, height=30, centerX=60, centerY=25, viewport_x=10, viewport_y=10, viewport_width=1920, viewport_height=1080))

    mock_candidates_locator = AsyncMock(spec=Locator)
    # Simulate a fast JS evaluation
    async def mock_evaluate_all(*args, **kwargs):
        return [1, 15.5]
    mock_candidates_locator.evaluate_all.side_effect = mock_evaluate_all

    mock_healed_locator = AsyncMock(spec=Locator)
    mock_healed_locator.text_content.return_value = "Submit"
    mock_candidates_locator.nth.return_value = mock_healed_locator

    page.get_by_role.return_value = mock_candidates_locator

    start_time = time.perf_counter()
    loc, _name, _dist = await SelfHealer.heal(page, ref_info)
    end_time = time.perf_counter()

    elapsed_ms = (end_time - start_time) * 1000
    assert loc is not None
    assert elapsed_ms < 50.0  # Should be virtually instantaneous in Python side, well under 50ms.
    print(f"\n[Performance] SelfHealer.heal executed in {elapsed_ms:.2f} ms")

@pytest.mark.asyncio
async def test_self_healer_no_bbox():
    page = AsyncMock(spec=Page)
    ref_info = RefInfo(role="button", name="Submit", nth=0, bbox=None)
    loc, name, dist = await SelfHealer.heal(page, ref_info)
    assert loc is None
    assert name is None
    assert dist == 0.0

@pytest.mark.asyncio
async def test_self_healer_success():
    page = AsyncMock(spec=Page)
    ref_info = RefInfo(role="button", name="Submit", nth=0, bbox=BBox(x=10, y=10, width=100, height=30, centerX=60, centerY=25, viewport_x=10, viewport_y=10, viewport_width=1920, viewport_height=1080))

    mock_candidates_locator = AsyncMock(spec=Locator)
    # Return index 1 as the best match and distance 15.5
    mock_candidates_locator.evaluate_all.return_value = [1, 15.5]

    mock_healed_locator = AsyncMock(spec=Locator)
    mock_healed_locator.text_content.return_value = "Submit (Healed)"
    mock_candidates_locator.nth.return_value = mock_healed_locator

    page.get_by_role.return_value = mock_candidates_locator

    loc, name, dist = await SelfHealer.heal(page, ref_info)

    assert loc is mock_healed_locator
    assert name == "Submit (Healed)"
    assert dist == 15.5
    page.get_by_role.assert_called_once_with("button")
    mock_candidates_locator.evaluate_all.assert_called_once()
    args = mock_candidates_locator.evaluate_all.call_args[0][1]
    assert args["origX"] == 60
    assert args["origY"] == 25
    assert args["origName"] == "Submit"
    assert args["origRole"] == "button"

@pytest.mark.asyncio
async def test_self_healer_cursor_roles():
    page = AsyncMock(spec=Page)
    ref_info = RefInfo(role="clickable", name="Click Me", nth=0, bbox=BBox(x=10, y=10, width=100, height=30, centerX=60, centerY=25, viewport_x=10, viewport_y=10, viewport_width=1920, viewport_height=1080))

    mock_candidates_locator = AsyncMock(spec=Locator)
    mock_candidates_locator.evaluate_all.return_value = -1 # No match found

    page.locator.return_value = mock_candidates_locator

    loc, name, dist = await SelfHealer.heal(page, ref_info)

    assert loc is None
    assert name is None
    assert dist == 0.0
    # For CURSOR_ROLES, we use page.locator with a CSS selector
    page.locator.assert_called_once()
    assert "a, button, input" in page.locator.call_args[0][0]
