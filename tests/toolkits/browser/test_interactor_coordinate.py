"""Tests for Interactor.interact_at() coordinate-based interaction (Visual Mode)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.session.interactor import Interactor

_WAIT_PATCH = "myrm_agent_harness.toolkits.browser.wait.wait_for_page_ready"


@pytest.fixture
def mock_page() -> Any:
    """Mock Playwright Page with mouse/keyboard APIs."""
    page = MagicMock()
    page.mouse = MagicMock()
    page.mouse.move = AsyncMock()
    page.mouse.click = AsyncMock()
    page.mouse.dblclick = AsyncMock()
    page.mouse.down = AsyncMock()
    page.mouse.up = AsyncMock()
    page.mouse.wheel = AsyncMock()
    page.keyboard = MagicMock()
    page.keyboard.type = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.evaluate = AsyncMock()
    page.viewport_size = {"width": 1280, "height": 720}
    page.locator = MagicMock()
    return page


@pytest.fixture
def interactor(mock_page: Any) -> Interactor:
    """Create Interactor with empty refs (coordinate mode doesn't use refs)."""
    return Interactor(mock_page, {})


@pytest.fixture(autouse=True)
def _instant_sleep() -> None:
    """Make every unit test instant — no real asyncio.sleep waits."""
    with patch("asyncio.sleep", new=AsyncMock()):
        yield


# =============================================================================
# Action: click at coordinates
# =============================================================================


@pytest.mark.asyncio
async def test_interact_at_click(interactor: Interactor, mock_page: Any) -> None:
    """Click at viewport coordinates."""
    with patch(_WAIT_PATCH, new_callable=AsyncMock):
        result = await interactor.interact_at("click", 400, 300)

    assert "Clicked at (400, 300)" in result
    mock_page.mouse.down.assert_awaited_once()
    mock_page.mouse.up.assert_awaited_once()
    assert interactor._mouse_x == 400
    assert interactor._mouse_y == 300


@pytest.mark.asyncio
async def test_interact_at_dblclick(interactor: Interactor, mock_page: Any) -> None:
    """Double-click at viewport coordinates."""
    with patch(_WAIT_PATCH, new_callable=AsyncMock):
        result = await interactor.interact_at("dblclick", 500, 400)

    assert "Double-clicked at (500, 400)" in result
    mock_page.mouse.dblclick.assert_awaited_once_with(500, 400)


# =============================================================================
# Action: type at coordinates
# =============================================================================


@pytest.mark.asyncio
async def test_interact_at_type(interactor: Interactor, mock_page: Any) -> None:
    """Type text at viewport coordinates."""
    with patch(_WAIT_PATCH, new_callable=AsyncMock):
        result = await interactor.interact_at("type", 400, 300, text="Hello World")

    assert "Typed 'Hello World' at (400, 300)" in result
    mock_page.mouse.click.assert_awaited_once_with(400, 300)
    mock_page.keyboard.type.assert_awaited_once()
    call_args = mock_page.keyboard.type.call_args
    assert call_args[0][0] == "Hello World"


@pytest.mark.asyncio
async def test_interact_at_type_no_text_raises(interactor: Interactor) -> None:
    """Type without text should raise ValueError."""
    with pytest.raises(ValueError, match="'text' is required"):
        await interactor.interact_at("type", 400, 300, text="")


# =============================================================================
# Action: press at coordinates
# =============================================================================


@pytest.mark.asyncio
async def test_interact_at_press(interactor: Interactor, mock_page: Any) -> None:
    """Press key combo at coordinates."""
    with patch(_WAIT_PATCH, new_callable=AsyncMock):
        result = await interactor.interact_at("press", 400, 300, text="Enter")

    assert "Pressed 'Enter' at (400, 300)" in result
    mock_page.keyboard.press.assert_awaited_once_with("Enter")


@pytest.mark.asyncio
async def test_interact_at_press_no_text_raises(interactor: Interactor) -> None:
    """Press without key combo should raise ValueError."""
    with pytest.raises(ValueError, match=r"'text'.*required"):
        await interactor.interact_at("press", 400, 300, text="")


# =============================================================================
# Action: hover at coordinates
# =============================================================================


@pytest.mark.asyncio
async def test_interact_at_hover(interactor: Interactor, mock_page: Any) -> None:
    """Hover at viewport coordinates."""
    result = await interactor.interact_at("hover", 600, 400)

    assert "Hovered at (600, 400)" in result
    mock_page.mouse.move.assert_awaited_once_with(600, 400)
    assert interactor._mouse_x == 600
    assert interactor._mouse_y == 400


# =============================================================================
# Action: scroll at coordinates
# =============================================================================


def _scroll_feed(mock_page: Any, *, movable: bool = True) -> None:
    """Wire evaluate/mouse.wheel so the scroll target container moves (or not)."""
    state = {"top": 0.0, "height": 2000.0, "client": 720.0}

    async def mock_evaluate(expr: str, arg: Any = None) -> Any:
        if "elementFromPoint" in expr:
            return dict(state)
        return 0

    async def mock_wheel(_dx: int, dy: int) -> None:
        if movable:
            state["top"] = min(state["top"] + dy, max(0.0, state["height"] - state["client"]))

    mock_page.evaluate = AsyncMock(side_effect=mock_evaluate)
    mock_page.mouse.wheel = AsyncMock(side_effect=mock_wheel)


@pytest.mark.asyncio
async def test_interact_at_scroll(interactor: Interactor, mock_page: Any) -> None:
    """Scroll at viewport coordinates."""
    _scroll_feed(mock_page)

    result = await interactor.interact_at("scroll", 640, 360, text="300")

    assert "Scrolled 300px at (640, 360)" in result
    mock_page.mouse.wheel.assert_awaited_once_with(0, 300)


@pytest.mark.asyncio
async def test_interact_at_scroll_negative(interactor: Interactor, mock_page: Any) -> None:
    """Scroll up (negative delta) at coordinates."""
    _scroll_feed(mock_page, movable=False)

    result = await interactor.interact_at("scroll", 640, 360, text="-200")

    assert "Scrolled -200px" in result
    mock_page.mouse.wheel.assert_awaited_once_with(0, -200)


@pytest.mark.asyncio
async def test_interact_at_scroll_no_move_reports_edge(interactor: Interactor, mock_page: Any) -> None:
    """Scroll that cannot move (stuck container) is reported honestly."""
    _scroll_feed(mock_page, movable=False)

    result = await interactor.interact_at("scroll", 640, 360, text="300")

    assert "(no visible movement" in result


@pytest.mark.asyncio
async def test_interact_at_scroll_invalid_delta(interactor: Interactor) -> None:
    """Scroll with non-numeric delta should raise ValueError."""
    with pytest.raises(ValueError, match="numeric text"):
        await interactor.interact_at("scroll", 640, 360, text="abc")


@pytest.mark.asyncio
async def test_interact_at_scroll_no_text_raises(interactor: Interactor) -> None:
    """Scroll without delta should raise ValueError."""
    with pytest.raises(ValueError, match=r"'text'.*required"):
        await interactor.interact_at("scroll", 640, 360, text="")


# =============================================================================
# Action: drag at coordinates
# =============================================================================


@pytest.mark.asyncio
async def test_interact_at_drag(interactor: Interactor, mock_page: Any) -> None:
    """Drag from one position to another."""
    with patch(_WAIT_PATCH, new_callable=AsyncMock):
        result = await interactor.interact_at(
            "drag",
            100,
            200,
            target_x=500,
            target_y=400,
        )

    assert "Dragged from (100, 200) to (500, 400)" in result
    mock_page.mouse.down.assert_awaited_once()
    mock_page.mouse.up.assert_awaited_once()
    assert interactor._mouse_x == 500
    assert interactor._mouse_y == 400


@pytest.mark.asyncio
async def test_interact_at_drag_missing_target(interactor: Interactor) -> None:
    """Drag without target coordinates should raise ValueError."""
    with pytest.raises(ValueError, match="'target_x' and 'target_y' are required"):
        await interactor.interact_at("drag", 100, 200)


@pytest.mark.asyncio
async def test_interact_at_drag_target_out_of_bounds(interactor: Interactor) -> None:
    """Drag target out of viewport bounds should raise ValueError."""
    with pytest.raises(ValueError, match="out of viewport bounds"):
        await interactor.interact_at("drag", 100, 200, target_x=2000, target_y=400)


# =============================================================================
# Validation: bounds checking
# =============================================================================


@pytest.mark.asyncio
async def test_interact_at_out_of_bounds(interactor: Interactor) -> None:
    """Coordinates outside viewport should raise ValueError."""
    with pytest.raises(ValueError, match="out of viewport bounds"):
        await interactor.interact_at("click", 1500, 300)


@pytest.mark.asyncio
async def test_interact_at_negative_coords(interactor: Interactor) -> None:
    """Negative coordinates should raise ValueError."""
    with pytest.raises(ValueError, match="out of viewport bounds"):
        await interactor.interact_at("click", -10, 300)


# =============================================================================
# Validation: unsupported actions
# =============================================================================


@pytest.mark.asyncio
async def test_interact_at_invalid_action(interactor: Interactor) -> None:
    """Unsupported coordinate action should raise ValueError."""
    with pytest.raises(ValueError, match="Invalid coordinate action"):
        await interactor.interact_at("fill", 400, 300)


@pytest.mark.asyncio
async def test_interact_at_upload_not_supported(interactor: Interactor) -> None:
    """upload_file is ref-only, not supported in coordinate mode."""
    with pytest.raises(ValueError, match="Invalid coordinate action"):
        await interactor.interact_at("upload_file", 400, 300)


# =============================================================================
# Bézier mouse integration
# =============================================================================


@pytest.mark.asyncio
async def test_interact_at_click_with_bezier(mock_page: Any) -> None:
    """Click with Bézier mouse enabled should call bezier_move."""
    from myrm_agent_harness.toolkits.browser.pool.config import (
        HumanizeConfig,
        HumanizeMode,
    )

    cfg = HumanizeConfig(mode=HumanizeMode.CAREFUL, enable_bezier_mouse=True)
    interactor = Interactor(mock_page, {}, humanize=cfg)

    with (
        patch(
            "myrm_agent_harness.toolkits.browser.session.interactor_coord_mixin.bezier_move",
            new_callable=AsyncMock,
        ) as mock_bezier,
        patch(_WAIT_PATCH, new_callable=AsyncMock),
    ):
        result = await interactor.interact_at("click", 400, 300)

    assert "Clicked at (400, 300)" in result
    mock_bezier.assert_awaited_once()


@pytest.mark.asyncio
async def test_interact_at_drag_with_bezier(mock_page: Any) -> None:
    """Drag with Bézier mouse should call bezier_move twice (start + end)."""
    from myrm_agent_harness.toolkits.browser.pool.config import (
        HumanizeConfig,
        HumanizeMode,
    )

    cfg = HumanizeConfig(mode=HumanizeMode.CAREFUL, enable_bezier_mouse=True)
    interactor = Interactor(mock_page, {}, humanize=cfg)

    with (
        patch(
            "myrm_agent_harness.toolkits.browser.session.interactor_coord_mixin.bezier_move",
            new_callable=AsyncMock,
        ) as mock_bezier,
        patch(_WAIT_PATCH, new_callable=AsyncMock),
    ):
        result = await interactor.interact_at("drag", 100, 200, target_x=500, target_y=400)

    assert "Dragged from" in result
    assert mock_bezier.await_count == 2


# =============================================================================
# Edge cases
# =============================================================================


@pytest.mark.asyncio
async def test_interact_at_boundary_coords(interactor: Interactor, mock_page: Any) -> None:
    """Coordinates at exact viewport boundary should succeed."""
    with patch(_WAIT_PATCH, new_callable=AsyncMock):
        result = await interactor.interact_at("click", 0, 0)
    assert "Clicked at (0, 0)" in result

    with patch(_WAIT_PATCH, new_callable=AsyncMock):
        result = await interactor.interact_at("click", 1280, 720)
    assert "Clicked at (1280, 720)" in result


@pytest.mark.asyncio
async def test_interact_at_updates_mouse_position(interactor: Interactor, mock_page: Any) -> None:
    """Mouse position should update after each coordinate interaction."""
    with patch(_WAIT_PATCH, new_callable=AsyncMock):
        await interactor.interact_at("click", 100, 200)
    assert interactor._mouse_x == 100
    assert interactor._mouse_y == 200

    await interactor.interact_at("hover", 300, 400)
    assert interactor._mouse_x == 300
    assert interactor._mouse_y == 400


# =============================================================================
# Additional coverage: type with Bézier, SPA wait degradation
# =============================================================================


@pytest.mark.asyncio
async def test_interact_at_type_with_bezier(mock_page: Any) -> None:
    """Type with Bézier mouse enabled calls bezier_move before the click."""
    from myrm_agent_harness.toolkits.browser.pool.config import (
        HumanizeConfig,
        HumanizeMode,
    )

    cfg = HumanizeConfig(mode=HumanizeMode.CAREFUL, enable_bezier_mouse=True)
    interactor = Interactor(mock_page, {}, humanize=cfg)

    with (
        patch(
            "myrm_agent_harness.toolkits.browser.session.interactor_coord_mixin.bezier_move",
            new_callable=AsyncMock,
        ) as mock_bezier,
        patch(_WAIT_PATCH, new_callable=AsyncMock),
    ):
        result = await interactor.interact_at("type", 400, 300, text="hi")

    assert "Typed 'hi'" in result
    mock_bezier.assert_awaited_once()


@pytest.mark.asyncio
async def test_interact_at_spa_wait_failure_degrades(interactor: Interactor, mock_page: Any) -> None:
    """A failing post-action SPA wait degrades silently (action still succeeds)."""
    with patch(_WAIT_PATCH, side_effect=Exception("wait failed")):
        result = await interactor.interact_at("click", 400, 300)

    assert "Clicked at (400, 300)" in result
    mock_page.mouse.down.assert_awaited_once()


@pytest.mark.asyncio
async def test_interact_at_hover_with_bezier(mock_page: Any) -> None:
    """Hover with Bézier mouse enabled calls bezier_move."""
    from myrm_agent_harness.toolkits.browser.pool.config import (
        HumanizeConfig,
        HumanizeMode,
    )

    cfg = HumanizeConfig(mode=HumanizeMode.CAREFUL, enable_bezier_mouse=True)
    interactor = Interactor(mock_page, {}, humanize=cfg)

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor_coord_mixin.bezier_move",
        new_callable=AsyncMock,
    ) as mock_bezier:
        result = await interactor.interact_at("hover", 400, 300)

    assert "Hovered at (400, 300)" in result
    mock_bezier.assert_awaited_once()


@pytest.mark.asyncio
async def test_interact_at_unknown_coord_action_reports(mock_page: Any) -> None:
    """An action that slips past validation reports instead of raising."""
    from myrm_agent_harness.toolkits.browser.session import (
        interactor_coord_mixin as coord_mod,
    )

    original = coord_mod.CoordInteractMixin._COORD_ACTIONS
    coord_mod.CoordInteractMixin._COORD_ACTIONS = frozenset(original | {"mystery"})
    try:
        result = await Interactor(mock_page, {}).interact_at("mystery", 100, 100)
    finally:
        coord_mod.CoordInteractMixin._COORD_ACTIONS = original

    assert result == "Unknown coordinate action: mystery"
