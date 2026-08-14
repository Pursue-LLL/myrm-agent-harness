"""Comprehensive tests for Interactor (100% coverage)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.exceptions import (
    ClickTargetUnreachableError,
    RefNotFoundError,
)
from myrm_agent_harness.toolkits.browser.pool.config import HumanizeConfig, HumanizeMode
from myrm_agent_harness.toolkits.browser.session.interactor import Interactor
from myrm_agent_harness.toolkits.browser.session.interactor_scroll_mixin import (
    _SCROLL_MEASURE_JS,
    _parse_scroll_params,
)
from myrm_agent_harness.toolkits.browser.snapshot import RefInfo


@pytest.fixture
def ref_info() -> RefInfo:
    """Sample RefInfo."""
    return RefInfo(
        role="button",
        name="Click Me",
        nth=None,
        bbox={"x": 100, "y": 50, "width": 80, "height": 30},
        position="center-center",
    )


@pytest.fixture
def refs_map(ref_info: RefInfo) -> dict[str, RefInfo]:
    """Sample refs mapping."""
    return {"e0": ref_info}


@pytest.fixture
def mock_page() -> Any:
    """Mock Playwright Page."""
    page = MagicMock()
    page.evaluate = AsyncMock()
    page.locator = MagicMock()
    page.viewport_size = {"width": 1280, "height": 720}
    page.mouse = MagicMock()
    page.mouse.move = AsyncMock()
    page.mouse.wheel = AsyncMock()
    return page


@pytest.fixture
def interactor(mock_page: Any, refs_map: dict[str, RefInfo]) -> Interactor:
    """Create Interactor with mocked page and refs."""
    return Interactor(mock_page, refs_map)


@pytest.fixture(autouse=True)
def _instant_sleep() -> None:
    """Make every unit test instant — no real asyncio.sleep waits."""
    with patch("asyncio.sleep", new=AsyncMock()):
        yield


# =============================================================================
# Initialization
# =============================================================================


def test_interactor_init(mock_page: Any, refs_map: dict[str, RefInfo]) -> None:
    """Test Interactor initialization."""
    interactor = Interactor(mock_page, refs_map)

    assert interactor._page is mock_page
    assert interactor._refs == refs_map


def test_interactor_update_refs(interactor: Interactor, ref_info: RefInfo) -> None:
    """Test update_refs method."""
    new_refs = {"e1": ref_info}

    interactor.update_refs(new_refs)

    assert interactor._refs == new_refs


# =============================================================================
# Action: click
# =============================================================================


@pytest.mark.asyncio
async def test_interact_click(interactor: Interactor) -> None:
    """Test click action."""
    mock_locator = AsyncMock()

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("click", "e0")

        assert result == "Clicked e0"
        mock_locator.click.assert_called_once()
        _, kwargs = mock_locator.click.call_args
        assert kwargs["timeout"] == 10_000
        assert "delay" in kwargs


# =============================================================================
# Action: dblclick
# =============================================================================


@pytest.mark.asyncio
async def test_interact_dblclick(interactor: Interactor) -> None:
    """Test double-click action."""
    mock_locator = AsyncMock()

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("dblclick", "e0")

        assert result == "Double-clicked e0"
        mock_locator.dblclick.assert_called_once()
        _, kwargs = mock_locator.dblclick.call_args
        assert kwargs["timeout"] == 10_000
        assert "delay" in kwargs


# =============================================================================
# Action: type
# =============================================================================


@pytest.mark.asyncio
async def test_interact_type(interactor: Interactor) -> None:
    """Test type action."""
    mock_locator = AsyncMock()
    mock_locator.get_attribute.return_value = "text"

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("type", "e0", "Hello World")

        assert result == "Typed 'Hello World' into e0"
        mock_locator.type.assert_called_once()
        args, kwargs = mock_locator.type.call_args
        assert args[0] == "Hello World"
        assert kwargs["timeout"] >= 10_000
        assert "delay" in kwargs


# =============================================================================
# Action: fill
# =============================================================================


@pytest.mark.asyncio
async def test_interact_fill(interactor: Interactor) -> None:
    """Test fill action."""
    mock_locator = AsyncMock()
    mock_locator.get_attribute.return_value = "text"

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("fill", "e0", "test@example.com")

        assert result == "Filled e0 with 'test@example.com'"
        mock_locator.fill.assert_called_once_with("test@example.com", timeout=10_000)


# =============================================================================
# Action: press
# =============================================================================


@pytest.mark.asyncio
async def test_interact_press(interactor: Interactor) -> None:
    """Test press action."""
    mock_locator = AsyncMock()

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("press", "e0", "Enter")

        assert result == "Pressed 'Enter' on e0"
        mock_locator.press.assert_called_once_with("Enter", timeout=10_000)


# =============================================================================
# Action: hover
# =============================================================================


@pytest.mark.asyncio
async def test_interact_hover(interactor: Interactor) -> None:
    """Test hover action."""
    mock_locator = AsyncMock()

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("hover", "e0")

        assert result == "Hovered over e0"
        mock_locator.hover.assert_called_once_with(timeout=10_000)


@pytest.mark.asyncio
async def test_interact_hover_bezier_success(
    mock_page: Any, refs_map: dict[str, RefInfo]
) -> None:
    """Test hover in CAREFUL mode uses Bézier trajectory when bounding_box succeeds."""
    from myrm_agent_harness.toolkits.browser.pool.config import (
        HumanizeConfig,
        HumanizeMode,
    )

    cfg = HumanizeConfig.from_mode(HumanizeMode.CAREFUL)
    interactor = Interactor(mock_page, refs_map, humanize=cfg)

    # evaluate feeds _ensure_target_in_view's rendered-state probe: an AsyncMock
    # default would return an un-awaited coroutine from probe.get(...) and leak a
    # RuntimeWarning. A real dict makes the probe resolve to "visible, top frame,
    # inside the center band" so the pre-interaction scroll exits on the first loop.
    mock_locator = AsyncMock()
    mock_locator.bounding_box = AsyncMock(
        return_value={"x": 100, "y": 300, "width": 80, "height": 30}
    )
    mock_locator.evaluate = AsyncMock(
        return_value={
            "x": 100.0,
            "y": 300.0,
            "width": 80.0,
            "height": 30.0,
            "visible": True,
            "is_top": True,
            "container": None,
        }
    )
    mock_page.mouse = MagicMock()
    mock_page.mouse.move = AsyncMock()
    mock_page.mouse.wheel = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.viewport_size = {"width": 800, "height": 600}

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("hover", "e0")

    assert result == "Hovered over e0"
    mock_locator.hover.assert_not_called()
    assert mock_page.mouse.move.call_count >= 1


@pytest.mark.asyncio
async def test_interact_hover_bezier_fallback(
    mock_page: Any, refs_map: dict[str, RefInfo]
) -> None:
    """Test hover in CAREFUL mode falls back to locator.hover() when bounding_box returns None."""
    from myrm_agent_harness.toolkits.browser.pool.config import (
        HumanizeConfig,
        HumanizeMode,
    )

    cfg = HumanizeConfig.from_mode(HumanizeMode.CAREFUL)
    interactor = Interactor(mock_page, refs_map, humanize=cfg)

    mock_locator = AsyncMock()
    mock_locator.bounding_box = AsyncMock(return_value=None)

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("hover", "e0")

    assert result == "Hovered over e0"
    mock_locator.hover.assert_called_once_with(timeout=10_000)


# =============================================================================
# Action: focus
# =============================================================================


@pytest.mark.asyncio
async def test_interact_focus(interactor: Interactor) -> None:
    """Test focus action."""
    mock_locator = AsyncMock()

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("focus", "e0")

        assert result == "Focused e0"
        mock_locator.focus.assert_called_once_with(timeout=10_000)


# =============================================================================
# Action: select
# =============================================================================


@pytest.mark.asyncio
async def test_interact_select(interactor: Interactor) -> None:
    """Test select action."""
    mock_locator = AsyncMock()

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("select", "e0", "option1")

        assert result == "Selected 'option1' in e0"
        mock_locator.select_option.assert_called_once_with("option1", timeout=10_000)


@pytest.mark.asyncio
async def test_interact_select_multi_value(interactor: Interactor) -> None:
    """Multi-select recordings join values with ';' — each option is selected."""
    mock_locator = AsyncMock()

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("select", "e0", "en; zh")

        assert result == "Selected 'en; zh' in e0"
        mock_locator.select_option.assert_called_once_with(["en", "zh"], timeout=10_000)


# =============================================================================
# Action: scroll
# =============================================================================


def _scroll_locator() -> AsyncMock:
    """Locator that resolves to a visible on-page element."""
    locator = AsyncMock()
    locator.bounding_box.return_value = {
        "x": 100,
        "y": 100,
        "width": 200,
        "height": 100,
    }
    return locator


@pytest.mark.asyncio
async def test_interact_scroll_positive(interactor: Interactor, mock_page: Any) -> None:
    """Test scroll action with positive delta (FAST: single wheel event, moved)."""
    mock_locator = _scroll_locator()
    _scroll_feed(mock_page, [2000, 2000])

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("scroll", "e0", "100")

    assert result == "Scrolled 100px"
    mock_locator.bounding_box.assert_called_once()
    mock_page.mouse.move.assert_called_once()
    mock_page.mouse.wheel.assert_called_once_with(0, 100)


@pytest.mark.asyncio
async def test_interact_scroll_negative(interactor: Interactor, mock_page: Any) -> None:
    """Test scroll action with negative delta (FAST: single wheel event, moved)."""
    mock_locator = _scroll_locator()
    _scroll_feed(mock_page, [2000, 2000], top=500)

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("scroll", "e0", "-50")

    assert result == "Scrolled -50px"
    mock_page.mouse.wheel.assert_called_once_with(0, -50)


@pytest.mark.asyncio
async def test_interact_scroll_at_bottom_reports_edge(
    interactor: Interactor, mock_page: Any
) -> None:
    """Scroll past the bottom edge reports the no-op honestly."""
    mock_locator = _scroll_locator()
    _scroll_feed(mock_page, [2000, 2000], client=720, top=1280)  # max scrollTop

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("scroll", "e0", "200")

    assert "(already at the bottom)" in result


@pytest.mark.asyncio
async def test_interact_scroll_no_overflow_reports(
    interactor: Interactor, mock_page: Any
) -> None:
    """Scroll on a non-scrollable container reports no overflow."""
    mock_locator = _scroll_locator()
    _scroll_feed(mock_page, [720, 720], client=720)

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("scroll", "e0", "100")

    assert "(no scrollable overflow)" in result


@pytest.mark.asyncio
async def test_interact_scroll_blocked_reports(
    interactor: Interactor, mock_page: Any
) -> None:
    """A scrollable container that ignores wheel input is reported honestly."""
    mock_locator = _scroll_locator()
    _scroll_feed(mock_page, [2000, 2000], advance=False, top=100)

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("scroll", "e0", "100")

    assert "(no visible movement" in result


@pytest.mark.asyncio
async def test_interact_scroll_invalid_text(interactor: Interactor) -> None:
    """Test scroll with invalid text raises ValueError."""
    mock_locator = AsyncMock()

    with (
        patch(
            "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
            return_value=mock_locator,
        ),
        pytest.raises(ValueError, match="Scroll requires numeric text"),
    ):
        await interactor.interact("scroll", "e0", "not_a_number")


# =============================================================================
# _ensure_target_in_view: humanized pre-interaction scroll (CAREFUL only)
# =============================================================================


def _careful_interactor(mock_page: Any, refs_map: dict[str, RefInfo]) -> Interactor:
    return Interactor(
        mock_page, refs_map, humanize=HumanizeConfig.from_mode(HumanizeMode.CAREFUL)
    )


def _probe(
    *,
    visible: bool = True,
    is_top: bool = True,
    x: float = 100,
    y: float = 0,
    width: float = 200,
    height: float = 100,
    container: dict | None = None,
) -> dict:
    """Rendered-state dict returned by _TARGET_PROBE_JS."""
    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "visible": visible,
        "is_top": is_top,
        "container": container,
    }


def _doc_container(delta: int) -> dict:
    """The main document as the scroll container."""
    return {
        "left": 0,
        "top": 0,
        "width": 1280,
        "height": 720,
        "is_doc": True,
        "delta": delta,
    }


@pytest.mark.asyncio
async def test_ensure_target_in_view_disabled_outside_careful(
    mock_page: Any, refs_map: dict[str, RefInfo]
) -> None:
    """FAST/DEFAULT never pre-scroll: the helper is a pure no-op."""
    for mode in (HumanizeMode.FAST, HumanizeMode.DEFAULT):
        interactor = Interactor(
            mock_page, refs_map, humanize=HumanizeConfig.from_mode(mode)
        )
        locator = AsyncMock()
        locator.bounding_box.return_value = {
            "x": 100,
            "y": 1800,
            "width": 200,
            "height": 100,
        }
        mock_page.mouse.wheel.reset_mock()
        moved = await interactor._ensure_target_in_view(locator)
        assert moved is False
        mock_page.mouse.wheel.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_target_in_view_already_in_zone_no_scroll(
    mock_page: Any, refs_map: dict[str, RefInfo]
) -> None:
    """A target already inside the center band costs zero wheel events."""
    interactor = _careful_interactor(mock_page, refs_map)
    locator = AsyncMock()
    locator.bounding_box.return_value = {
        "x": 100,
        "y": 300,
        "width": 200,
        "height": 100,
    }  # cy = 350, zone (0.3, 0.7) * 720 = (216, 504)
    locator.evaluate.return_value = _probe(y=300, container=_doc_container(0))
    mock_page.mouse.wheel = AsyncMock()

    moved = await interactor._ensure_target_in_view(locator)

    assert moved is False
    mock_page.mouse.wheel.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_target_in_view_scrolls_below_target(
    mock_page: Any, refs_map: dict[str, RefInfo]
) -> None:
    """A target below the viewport is wheeled toward it (humanized notches)."""
    interactor = _careful_interactor(mock_page, refs_map)
    locator = AsyncMock()
    locator.bounding_box.return_value = {
        "x": 100,
        "y": 1800,
        "width": 200,
        "height": 100,
    }  # off-viewport → probe reads invisible → main document container
    locator.evaluate.return_value = _probe(
        visible=False, y=1800, container=_doc_container(1490)
    )
    mock_page.mouse.wheel = AsyncMock()

    with patch("random.random", return_value=0.5):  # no overshoot branch
        moved = await interactor._ensure_target_in_view(locator)

    assert moved is True
    assert mock_page.mouse.wheel.call_count >= 1


@pytest.mark.asyncio
async def test_ensure_target_in_view_scrolls_above_target(
    mock_page: Any, refs_map: dict[str, RefInfo]
) -> None:
    """A target above the viewport is wheeled up (negative delta)."""
    interactor = _careful_interactor(mock_page, refs_map)
    locator = AsyncMock()
    locator.bounding_box.return_value = {
        "x": 100,
        "y": -800,
        "width": 200,
        "height": 100,
    }  # cy = -750 < zone_lo = 216
    locator.evaluate.return_value = _probe(
        visible=False, y=-800, container=_doc_container(-1110)
    )
    mock_page.mouse.wheel = AsyncMock()

    with patch("random.random", return_value=0.5):
        moved = await interactor._ensure_target_in_view(locator)

    assert moved is True
    deltas = [c.args[1] for c in mock_page.mouse.wheel.call_args_list]
    assert all(d < 0 for d in deltas)


@pytest.mark.asyncio
async def test_ensure_target_in_view_measure_failure_no_scroll(
    mock_page: Any, refs_map: dict[str, RefInfo]
) -> None:
    """Unmeasurable targets degrade silently (no scroll, no crash)."""
    interactor = _careful_interactor(mock_page, refs_map)
    locator = AsyncMock()
    locator.bounding_box.return_value = None
    mock_page.mouse.wheel = AsyncMock()

    moved = await interactor._ensure_target_in_view(locator)

    assert moved is False
    mock_page.mouse.wheel.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_target_in_view_stops_when_target_enters_zone(
    mock_page: Any, refs_map: dict[str, RefInfo]
) -> None:
    """Per-step re-probe breaks the loop as soon as the target enters the zone."""
    interactor = _careful_interactor(mock_page, refs_map)
    locator = AsyncMock()
    # Read order: loop re-check box (below) + probe (invisible → container wheel),
    # then loop re-check box (inside zone) + probe (visible → break).
    locator.bounding_box.side_effect = [
        {"x": 100, "y": 1800, "width": 200, "height": 100},
        {"x": 100, "y": 300, "width": 200, "height": 100},
    ]
    locator.evaluate.side_effect = [
        _probe(visible=False, y=1800, container=_doc_container(1490)),
        _probe(y=300, container=_doc_container(0)),
    ]
    mock_page.mouse.wheel = AsyncMock()

    with (
        patch.object(interactor, "_scroll_deliver", new=AsyncMock()) as mock_deliver,
        patch("random.random", return_value=0.5),
    ):
        moved = await interactor._ensure_target_in_view(locator)

    assert moved is True
    mock_deliver.assert_awaited_once()  # re-probe breaks the loop right after


@pytest.mark.asyncio
async def test_ensure_target_in_view_degrades_on_wheel_error(
    mock_page: Any, refs_map: dict[str, RefInfo]
) -> None:
    """Wheel errors during the best-effort pre-scroll degrade silently."""
    interactor = _careful_interactor(mock_page, refs_map)
    locator = AsyncMock()
    locator.bounding_box.return_value = {
        "x": 100,
        "y": 1800,
        "width": 200,
        "height": 100,
    }
    locator.evaluate.return_value = _probe(
        visible=False, y=1800, container=_doc_container(1490)
    )
    mock_page.mouse.wheel = AsyncMock(side_effect=Exception("Target closed"))

    moved = await interactor._ensure_target_in_view(locator)

    assert moved is False


@pytest.mark.asyncio
async def test_ensure_target_in_view_scrolls_nested_container(
    mock_page: Any, refs_map: dict[str, RefInfo]
) -> None:
    """A target clipped by an inner scroller wheels that scroller, not the page.

    The geometry lies inside the page viewport (y=601) so the old zone check
    wrongly treated it as in-view; the rendered probe reads it invisible and
    scrolls the nested overflow:auto ancestor instead.
    """
    interactor = _careful_interactor(mock_page, refs_map)
    locator = AsyncMock()
    locator.bounding_box.return_value = {
        "x": 21,
        "y": 601,
        "width": 100,
        "height": 40,
    }
    locator.evaluate.side_effect = [
        _probe(
            visible=False,
            x=21,
            y=601,
            width=100,
            height=40,
            container={
                "left": 21,
                "top": 0,
                "width": 300,
                "height": 120,
                "is_doc": False,
                "delta": 561,
            },
        ),
        _probe(
            visible=True,
            x=21,
            y=601,
            width=100,
            height=40,
            container={
                "left": 21,
                "top": 0,
                "width": 300,
                "height": 120,
                "is_doc": False,
                "delta": 0,
            },
        ),
    ]
    mock_page.mouse.wheel = AsyncMock()

    with (
        patch.object(interactor, "_scroll_deliver", new=AsyncMock()) as mock_deliver,
        patch.object(interactor, "_scroll_move_cursor", new=AsyncMock()) as mock_move,
    ):
        moved = await interactor._ensure_target_in_view(locator)

    assert moved is True
    mock_deliver.assert_awaited_once_with(561)
    # wheel dispatch lands inside the scroller (its center), not on the target
    args, _kwargs = mock_move.await_args
    assert args[0] == 171.0  # cx 71 + (container cx 171 - probe cx 71) = 171
    assert args[1] == 60.0  # cy 621 + (container cy 60 - probe cy 621) = 60


@pytest.mark.asyncio
async def test_ensure_target_in_view_visible_in_nested_container_breaks(
    mock_page: Any, refs_map: dict[str, RefInfo]
) -> None:
    """A nested-container target already visible needs no further scrolling."""
    interactor = _careful_interactor(mock_page, refs_map)
    locator = AsyncMock()
    locator.bounding_box.return_value = {
        "x": 21,
        "y": 601,
        "width": 100,
        "height": 40,
    }
    locator.evaluate.return_value = _probe(
        visible=True,
        y=601,
        width=100,
        height=40,
        container={
            "left": 21,
            "top": 0,
            "width": 300,
            "height": 120,
            "is_doc": False,
            "delta": 0,
        },
    )
    mock_page.mouse.wheel = AsyncMock()

    moved = await interactor._ensure_target_in_view(locator)

    assert moved is False
    mock_page.mouse.wheel.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_target_in_view_visible_in_iframe_breaks(
    mock_page: Any, refs_map: dict[str, RefInfo]
) -> None:
    """An iframe target already visible stops — the page band is meaningless there."""
    interactor = _careful_interactor(mock_page, refs_map)
    locator = AsyncMock()
    locator.bounding_box.return_value = {
        "x": 45,
        "y": 76,
        "width": 100,
        "height": 40,
    }
    locator.evaluate.return_value = _probe(
        visible=True,
        is_top=False,
        y=55,
        width=100,
        height=40,
        container={
            "left": 0,
            "top": 0,
            "width": 400,
            "height": 150,
            "is_doc": True,
            "delta": 0,
        },
    )
    mock_page.mouse.wheel = AsyncMock()

    moved = await interactor._ensure_target_in_view(locator)

    assert moved is False
    mock_page.mouse.wheel.assert_not_called()


@pytest.mark.asyncio
async def test_interact_click_careful_pre_scrolls(mock_page: Any) -> None:
    """CAREFUL click on an off-band target humanized-wheels it into view first."""
    refs = {
        "e0": RefInfo(
            role="button",
            name="Click Me",
            nth=None,
            bbox={"x": 100, "y": 50},
            position="center-center",
        )
    }
    interactor = _careful_interactor(mock_page, refs)
    locator = AsyncMock()
    # Read order: initial target check (below) -> cursor-target clamp (below) ->
    # loop re-check (still below, one deliver) -> loop re-check (now in zone) ->
    # _bezier_move_to (in viewport, Bézier proceeds).
    locator.bounding_box.side_effect = [
        {"x": 100, "y": 1800, "width": 200, "height": 100},  # cy = 1850 > 504
        {"x": 100, "y": 1800, "width": 200, "height": 100},
        {"x": 100, "y": 1800, "width": 200, "height": 100},
        {"x": 100, "y": 400, "width": 200, "height": 100},  # cy = 450 in zone
        {"x": 100, "y": 400, "width": 200, "height": 100},  # inside viewport
    ]
    locator.evaluate.side_effect = [
        _probe(visible=False, y=1800, container=_doc_container(1490)),
        _probe(visible=False, y=1800, container=_doc_container(1490)),
        _probe(visible=False, y=1800, container=_doc_container(1490)),
        _probe(y=400, container=_doc_container(0)),
    ]
    mock_page.mouse = MagicMock()
    mock_page.mouse.move = AsyncMock()
    mock_page.mouse.wheel = AsyncMock()
    mock_page.mouse.down = AsyncMock()
    mock_page.mouse.up = AsyncMock()

    with (
        patch(
            "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
            return_value=locator,
        ),
        patch("random.random", return_value=0.5),
    ):
        result = await interactor.interact("click", "e0")

    assert "Clicked e0" in result
    assert mock_page.mouse.wheel.call_count >= 1
    locator.click.assert_not_called()  # CAREFUL uses Bézier + mouse.down/up
    mock_page.mouse.down.assert_awaited_once()
    mock_page.mouse.up.assert_awaited_once()


@pytest.mark.asyncio
async def test_interact_click_careful_locked_scroll_falls_back(mock_page: Any) -> None:
    """Locked scroll: CAREFUL click falls back to native locator.click.

    When the pre-interaction wheel cannot move the target into the viewport (e.g.
    body {overflow: hidden}), the Bézier move is refused for an off-viewport target
    and the click goes through the native path — scrollIntoViewIfNeeded either
    scrolls it in or fails loudly, never a silent click at the viewport edge.
    """
    refs = {
        "e0": RefInfo(
            role="button",
            name="Click Me",
            nth=None,
            bbox={"x": 100, "y": 50},
            position="center-center",
        )
    }
    interactor = _careful_interactor(mock_page, refs)
    locator = AsyncMock()
    locator.bounding_box.return_value = {
        "x": 100,
        "y": 1800,
        "width": 200,
        "height": 100,
    }  # cy = 1850 > zone_hi = 504; box never moves (scroll locked)
    locator.evaluate.return_value = _probe(
        visible=False, y=1800, container=_doc_container(1490)
    )
    mock_page.mouse = MagicMock()
    mock_page.mouse.move = AsyncMock()
    mock_page.mouse.wheel = AsyncMock()
    mock_page.mouse.down = AsyncMock()
    mock_page.mouse.up = AsyncMock()

    with (
        patch(
            "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
            return_value=locator,
        ),
        patch("random.random", return_value=0.5),
    ):
        result = await interactor.interact("click", "e0")

    assert "Clicked e0" in result
    locator.click.assert_awaited_once()  # native fallback path
    mock_page.mouse.down.assert_not_called()
    mock_page.mouse.up.assert_not_called()


@pytest.mark.asyncio
async def test_interact_click_careful_unreachable_target_raises(
    mock_page: Any,
) -> None:
    """A target with no scroll path fails loudly instead of clicking at the edge."""
    refs = {
        "e0": RefInfo(
            role="button",
            name="Click Me",
            nth=None,
            bbox={"x": 100, "y": 50},
            position="center-center",
        )
    }
    interactor = _careful_interactor(mock_page, refs)
    locator = AsyncMock()
    locator.bounding_box.return_value = {
        "x": 100,
        "y": 1800,
        "width": 200,
        "height": 100,
    }  # off-viewport, never moves (scroll locked)
    locator.evaluate.return_value = _probe(visible=False, y=1800, container=None)
    mock_page.mouse = MagicMock()
    mock_page.mouse.move = AsyncMock()
    mock_page.mouse.wheel = AsyncMock()
    mock_page.mouse.down = AsyncMock()
    mock_page.mouse.up = AsyncMock()

    with (
        patch(
            "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
            return_value=locator,
        ),
        patch("random.random", return_value=0.5),
        pytest.raises(ClickTargetUnreachableError),
    ):
        await interactor.interact("click", "e0")

    locator.click.assert_not_called()


@pytest.mark.asyncio
async def test_interact_click_default_no_pre_scroll(
    interactor: Interactor, mock_page: Any
) -> None:
    """DEFAULT/FAST click never emits pre-interaction wheel events."""
    locator = AsyncMock()

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=locator,
    ):
        result = await interactor.interact("click", "e0")

    assert "Clicked e0" in result
    mock_page.mouse.wheel.assert_not_called()


# =============================================================================
# _scroll_deliver: mode-specific wheel delivery
# =============================================================================


def _wheel_deltas(mock_page: Any) -> list[int]:
    """Signed wheel deltas delivered via mouse.wheel, in call order."""
    return [call.args[1] for call in mock_page.mouse.wheel.call_args_list]


@pytest.mark.asyncio
async def test_scroll_deliver_fast_single_wheel(mock_page: Any) -> None:
    """FAST delivers the whole delta as one wheel event (zero humanization cost)."""
    interactor = Interactor(
        mock_page, {}, humanize=HumanizeConfig.from_mode(HumanizeMode.FAST)
    )

    await interactor._scroll_deliver(300)

    assert _wheel_deltas(mock_page) == [300]


@pytest.mark.asyncio
async def test_scroll_deliver_default_wheel_burst(mock_page: Any) -> None:
    """DEFAULT splits the delta into a burst of small wheel notches."""
    interactor = Interactor(
        mock_page, {}, humanize=HumanizeConfig.from_mode(HumanizeMode.DEFAULT)
    )

    await interactor._scroll_deliver(300)

    deltas = _wheel_deltas(mock_page)
    assert len(deltas) > 1, "expected a multi-event burst"
    assert sum(deltas) == 300


@pytest.mark.asyncio
async def test_scroll_deliver_careful_notch_rhythm(mock_page: Any) -> None:
    """CAREFUL delivers notches summing to the delta and settles without overshoot."""
    interactor = Interactor(
        mock_page, {}, humanize=HumanizeConfig.from_mode(HumanizeMode.CAREFUL)
    )

    with patch("random.random", return_value=0.5):  # no overshoot branch
        await interactor._scroll_deliver(300)

    deltas = _wheel_deltas(mock_page)
    assert len(deltas) > 1, "expected accel/cruise/decel notches"
    assert sum(deltas) == 300


# =============================================================================
# _parse_scroll_params
# =============================================================================


def test_parse_scroll_params_defaults() -> None:
    """Empty/None text returns all defaults."""
    result = _parse_scroll_params("")
    assert result["max_steps"] == 15
    assert result["delay_ms"] == 500
    assert result["stable_count"] == 3

    result_none = _parse_scroll_params(None)  # type: ignore[arg-type]
    assert result_none == result


def test_parse_scroll_params_custom_values() -> None:
    """Custom key=value pairs override defaults."""
    result = _parse_scroll_params("max_steps=30,delay_ms=200,stable_count=5")
    assert result["max_steps"] == 30
    assert result["delay_ms"] == 200
    assert result["stable_count"] == 5


def test_parse_scroll_params_partial() -> None:
    """Only specified keys are overridden."""
    result = _parse_scroll_params("delay_ms=100")
    assert result["max_steps"] == 15
    assert result["delay_ms"] == 100
    assert result["stable_count"] == 3


def test_parse_scroll_params_clamping() -> None:
    """Values are clamped to safe ranges."""
    result = _parse_scroll_params("max_steps=9999,delay_ms=10,stable_count=1")
    assert result["max_steps"] == 1000  # CAP
    assert result["delay_ms"] == 100  # min 100
    assert result["stable_count"] == 2  # min 2


def test_parse_scroll_params_invalid_values_ignored() -> None:
    """Non-numeric values and unknown keys are silently ignored."""
    result = _parse_scroll_params("max_steps=abc,unknown_key=42")
    assert result["max_steps"] == 15  # unchanged
    assert result["delay_ms"] == 500
    assert result["stable_count"] == 3


def test_parse_scroll_params_whitespace() -> None:
    """Whitespace around keys and values is trimmed."""
    result = _parse_scroll_params("  max_steps = 25 , delay_ms = 300 ")
    assert result["max_steps"] == 25
    assert result["delay_ms"] == 300


def test_parse_scroll_params_no_equals() -> None:
    """Plain text without = signs is ignored, returns defaults."""
    result = _parse_scroll_params("hello world")
    assert result["max_steps"] == 15
    assert result["delay_ms"] == 500
    assert result["stable_count"] == 3


def test_parse_scroll_params_negative_values() -> None:
    """Negative values are clamped to minimums."""
    result = _parse_scroll_params("max_steps=-5,delay_ms=-100,stable_count=-1")
    assert result["max_steps"] == 1  # min 1
    assert result["delay_ms"] == 100  # min 100
    assert result["stable_count"] == 2  # min 2


def test_parse_scroll_params_zero_max_steps() -> None:
    """max_steps=0 is clamped to 1."""
    result = _parse_scroll_params("max_steps=0")
    assert result["max_steps"] == 1


def test_scroll_measure_js_targets_wheel_scrollable_containers() -> None:
    """The measurement JS only treats real wheel-scrollable boxes as targets.

    Regression canary: a bare scrollHeight check would mis-measure overflow:visible
    boxes (their scrollTop is always 0), causing every wheel scroll over them to be
    falsely reported as stuck/no-op even though the document scrolls. Verified
    against a real browser (overflow:visible box skipped, document measured).
    """
    assert "isScrollable" in _SCROLL_MEASURE_JS
    assert "overflowY" in _SCROLL_MEASURE_JS
    assert "contentDocument" in _SCROLL_MEASURE_JS
    assert "HTMLIFrameElement" in _SCROLL_MEASURE_JS
    assert "elementFromPoint" in _SCROLL_MEASURE_JS


# =============================================================================
# Action: scroll_to_bottom
# =============================================================================


def _scroll_feed(
    mock_page: Any,
    heights: list[int],
    inner_height: int = 800,
    client: int = 800,
    advance: bool = True,
    top: float = 0.0,
) -> None:
    """Wire mock_page to simulate a page whose scrollHeight follows `heights`.

    Each wheel event advances scrollTop by the wheel delta until it reaches the
    container bottom (like a real browser clamps overscroll). When ``advance`` is
    False the wheel never moves scrollTop, simulating a stuck container.
    """
    state = {"top": float(top), "height": float(heights[0]), "client": float(client)}
    idx = {"i": 1}

    async def mock_evaluate(expr: str, arg: Any = None) -> Any:
        if "innerHeight" in expr:
            return inner_height
        if "elementFromPoint" in expr:
            if idx["i"] < len(heights):
                state["height"] = float(heights[idx["i"]])
                idx["i"] += 1
            return dict(state)
        return 0

    async def mock_wheel(_dx: int, dy: int) -> None:
        if advance:
            state["top"] = min(
                state["top"] + dy, max(0.0, state["height"] - state["client"])
            )

    mock_page.evaluate = AsyncMock(side_effect=mock_evaluate)
    mock_page.mouse.wheel = AsyncMock(side_effect=mock_wheel)


@pytest.mark.asyncio
async def test_scroll_to_bottom_reaches_bottom(
    interactor: Interactor, mock_page: Any
) -> None:
    """scroll_to_bottom stops when scrollHeight stabilizes."""
    mock_locator = _scroll_locator()
    _scroll_feed(mock_page, [1000, 1500, 2000, 2000, 2000, 2000])

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("scroll_to_bottom", "e0", "")

    assert "completed" in result
    assert "steps" in result.lower() or "Scrolled" in result
    assert mock_page.mouse.wheel.call_count >= 1


@pytest.mark.asyncio
async def test_scroll_to_bottom_max_steps_reached(
    interactor: Interactor, mock_page: Any
) -> None:
    """scroll_to_bottom respects max_steps when page keeps growing."""
    mock_locator = _scroll_locator()
    _scroll_feed(mock_page, [1000, 1500, 2000, 2500, 3000])

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("scroll_to_bottom", "e0", "max_steps=3")

    assert "max_reached" in result
    assert "3 steps" in result


@pytest.mark.asyncio
async def test_scroll_to_bottom_with_custom_params(
    interactor: Interactor, mock_page: Any
) -> None:
    """scroll_to_bottom accepts custom delay_ms and stable_count."""
    mock_locator = _scroll_locator()
    _scroll_feed(mock_page, [1000, 1000, 1000])

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact(
            "scroll_to_bottom", "e0", "delay_ms=200,stable_count=2"
        )

    assert "completed" in result


@pytest.mark.asyncio
async def test_scroll_to_bottom_single_step_already_at_bottom(
    interactor: Interactor, mock_page: Any
) -> None:
    """Page already at bottom returns completed after stable_count checks."""
    mock_locator = _scroll_locator()
    _scroll_feed(mock_page, [500, 500, 500, 500])

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("scroll_to_bottom", "e0", "")

    assert "completed" in result


@pytest.mark.asyncio
async def test_scroll_to_bottom_no_overflow_early_exit(
    interactor: Interactor, mock_page: Any
) -> None:
    """A non-scrollable container exits immediately without wheel events."""
    mock_locator = _scroll_locator()
    _scroll_feed(mock_page, [720, 720], client=720)

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("scroll_to_bottom", "e0", "")

    assert "0 steps" in result
    assert "completed" in result
    assert "no scrollable overflow" in result
    mock_page.mouse.wheel.assert_not_called()


@pytest.mark.asyncio
async def test_scroll_to_bottom_viewport_zero_fallback(
    interactor: Interactor, mock_page: Any
) -> None:
    """viewport_h <= 0 falls back to 800."""
    mock_locator = _scroll_locator()
    _scroll_feed(mock_page, [1000, 1000, 1000, 1000], inner_height=0)

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("scroll_to_bottom", "e0", "stable_count=2")

    assert "completed" in result


@pytest.mark.asyncio
async def test_scroll_to_bottom_height_output_format(
    interactor: Interactor, mock_page: Any
) -> None:
    """Return string contains steps, elapsed, height range, and status."""
    mock_locator = _scroll_locator()
    _scroll_feed(mock_page, [1000, 2000, 2000, 2000, 2000])

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("scroll_to_bottom", "e0", "")

    assert "Scrolled" in result
    assert "steps" in result
    assert "Height:" in result
    assert "Status:" in result
    assert "completed" in result


@pytest.mark.asyncio
async def test_scroll_to_bottom_stuck_repositions_once(
    interactor: Interactor, mock_page: Any
) -> None:
    """A scrollable container that ignores wheel input is retargeted once, then reported stuck."""
    mock_locator = _scroll_locator()
    _scroll_feed(mock_page, [1000, 1500, 2000, 2500, 2500], advance=False)

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("scroll_to_bottom", "e0", "")

    assert "stuck" in result
    assert mock_locator.bounding_box.call_count >= 2


# =============================================================================
# Action: upload_file
# =============================================================================


@pytest.mark.asyncio
async def test_interact_upload_file(interactor: Interactor) -> None:
    """Test upload_file action."""
    mock_locator = AsyncMock()

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("upload_file", "e0", "/tmp/file.txt")

        assert result == "Uploaded file to e0: /tmp/file.txt"
        mock_locator.set_input_files.assert_called_once_with(
            "/tmp/file.txt", timeout=10_000
        )


# =============================================================================
# Action: drag
# =============================================================================


@pytest.mark.asyncio
async def test_interact_drag_success(interactor: Interactor, mock_page: Any) -> None:
    """Test drag action with valid coordinates."""
    mock_locator = AsyncMock()
    body_locator = MagicMock()
    mock_page.locator.return_value = body_locator

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("drag", "e0", "200,150")

        assert result == "Dragged e0 to (200, 150)"
        mock_locator.drag_to.assert_called_once_with(
            body_locator, target_position={"x": 200, "y": 150}
        )


@pytest.mark.asyncio
async def test_interact_drag_invalid_format(interactor: Interactor) -> None:
    """Test drag with invalid text format."""
    mock_locator = AsyncMock()

    with (
        patch(
            "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
            return_value=mock_locator,
        ),
        pytest.raises(ValueError, match="Drag requires 'x,y' text"),
    ):
        await interactor.interact("drag", "e0", "invalid")


@pytest.mark.asyncio
async def test_interact_drag_non_numeric(interactor: Interactor) -> None:
    """Test drag with non-numeric coordinates."""
    mock_locator = AsyncMock()

    with (
        patch(
            "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
            return_value=mock_locator,
        ),
        pytest.raises(ValueError, match="Drag requires numeric 'x,y'"),
    ):
        await interactor.interact("drag", "e0", "abc,def")


# =============================================================================
# Action: check
# =============================================================================


@pytest.mark.asyncio
async def test_interact_check(interactor: Interactor) -> None:
    """Test check action."""
    mock_locator = AsyncMock()

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("check", "e0")

        assert result == "Checked e0"
        mock_locator.check.assert_called_once_with(timeout=10_000)


# =============================================================================
# Action: uncheck
# =============================================================================


@pytest.mark.asyncio
async def test_interact_uncheck(interactor: Interactor) -> None:
    """Test uncheck action."""
    mock_locator = AsyncMock()

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("uncheck", "e0")

        assert result == "Unchecked e0"
        mock_locator.uncheck.assert_called_once_with(timeout=10_000)


# =============================================================================
# Error cases
# =============================================================================


@pytest.mark.asyncio
async def test_interact_invalid_action(interactor: Interactor) -> None:
    """Test interact with invalid action raises ValueError."""
    with pytest.raises(ValueError, match="Invalid action"):
        await interactor.interact("invalid_action", "e0")


def test_metrics_empty():
    from myrm_agent_harness.toolkits.browser.session.ref_metrics import (
        RefNotFoundMetrics,
    )

    metrics = RefNotFoundMetrics()
    assert metrics.failure_rate == 0.0
    assert metrics.recent_failure_rate == 0.0
    assert metrics.top_failed_refs == []
    assert metrics.top_failed_actions == []
    d = metrics.to_dict()
    assert d["total_failures"] == 0


def test_metrics_caching():
    from myrm_agent_harness.toolkits.browser.session.ref_metrics import (
        RefNotFoundMetrics,
    )

    metrics = RefNotFoundMetrics()
    metrics.record_interaction(failed=True, ref="e1", action="click")
    assert metrics.top_failed_refs == [("e1", 1)]
    assert metrics.top_failed_actions == [("click", 1)]
    # Test cache
    assert metrics.top_failed_refs == [("e1", 1)]
    assert metrics.top_failed_actions == [("click", 1)]


from patchright.async_api import Page


def test_update_refs():
    page = AsyncMock(spec=Page)
    interactor = Interactor(page, {})
    interactor.update_refs(
        {"e1": RefInfo(role="link", name="L", nth=0)}, last_snapshot_url="http://new"
    )
    assert "e1" in interactor._refs
    assert interactor._last_snapshot_url == "http://new"


def test_get_context_refs_limit():
    page = AsyncMock(spec=Page)
    refs = {f"e{i}": RefInfo(role="link", name=f"L{i}", nth=0) for i in range(20)}
    interactor = Interactor(page, refs)
    res = interactor._get_context_refs(max_total=5)
    assert len(res) == 5


def test_metrics_property():
    page = AsyncMock(spec=Page)
    interactor = Interactor(page, {})
    from myrm_agent_harness.toolkits.browser.session.ref_metrics import (
        RefNotFoundMetrics,
    )

    assert isinstance(interactor.metrics, RefNotFoundMetrics)


def test_log_metrics_if_needed():
    page = AsyncMock(spec=Page)
    interactor = Interactor(page, {})
    interactor._metrics.total_interactions = 100
    interactor._metrics.total_failures = 1
    with patch(
        "myrm_agent_harness.toolkits.browser.session.ref_metrics.logger.info"
    ) as mock_info:
        interactor._log_metrics_if_needed()
        mock_info.assert_called_once()


def test_resolve_frame():
    page = AsyncMock(spec=Page)
    frame = AsyncMock()
    page.frames = [page, frame]
    interactor = Interactor(page, {})
    assert interactor._resolve_frame("f1_e0") == frame
    assert interactor._resolve_frame("f99_e0") == page
    assert interactor._resolve_frame("fX_e0") == page


@pytest.mark.asyncio
async def test_interact_exception_with_dialog():
    page = AsyncMock(spec=Page)
    interactor = Interactor(page, {"e0": RefInfo(role="button", name="B", nth=0)})

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator"
    ) as mock_resolve:
        mock_loc = AsyncMock()
        mock_loc.click.side_effect = Exception("TargetClosedError")
        mock_resolve.return_value = mock_loc

        with patch(
            "myrm_agent_harness.toolkits.computer_use.session.create_computer_session"
        ) as mock_create:
            mock_cu = AsyncMock()
            mock_cu.backend.has_blocking_dialog.return_value = True
            mock_create.return_value = mock_cu

            res = await interactor.interact("click", "e0")
            assert "CRITICAL WARNING" in res


@pytest.mark.asyncio
async def test_interact_exception_no_dialog():
    page = AsyncMock(spec=Page)
    interactor = Interactor(page, {"e0": RefInfo(role="button", name="B", nth=0)})

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator"
    ) as mock_resolve:
        mock_loc = AsyncMock()
        mock_loc.click.side_effect = Exception("TargetClosedError")
        mock_resolve.return_value = mock_loc

        with patch(
            "myrm_agent_harness.toolkits.computer_use.session.create_computer_session"
        ) as mock_create:
            mock_cu = AsyncMock()
            mock_cu.backend.has_blocking_dialog.return_value = False
            mock_create.return_value = mock_cu

            with pytest.raises(Exception, match="TargetClosedError"):
                await interactor.interact("click", "e0")


@pytest.mark.asyncio
async def test_interact_type_exception():
    page = AsyncMock(spec=Page)
    interactor = Interactor(page, {"e0": RefInfo(role="button", name="B", nth=0)})

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator"
    ) as mock_resolve:
        mock_loc = AsyncMock()
        mock_loc.get_attribute.side_effect = Exception("error")
        mock_resolve.return_value = mock_loc

        res = await interactor.interact("type", "e0", "test")
        assert "Typed 'test'" in res


@pytest.mark.asyncio
async def test_interact_fill_exception():
    page = AsyncMock(spec=Page)
    interactor = Interactor(page, {"e0": RefInfo(role="button", name="B", nth=0)})

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator"
    ) as mock_resolve:
        mock_loc = AsyncMock()
        mock_loc.get_attribute.side_effect = Exception("error")
        mock_resolve.return_value = mock_loc

        res = await interactor.interact("fill", "e0", "test")
        assert "Filled" in res


@pytest.mark.asyncio
async def test_interact_password_blocked():
    page = AsyncMock(spec=Page)
    interactor = Interactor(
        page, {"e0": RefInfo(role="textbox", name="Password", nth=0)}
    )

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator"
    ) as mock_resolve:
        mock_loc = AsyncMock()
        mock_loc.get_attribute.return_value = "password"
        mock_resolve.return_value = mock_loc

        with pytest.raises(
            ValueError,
            match="SecurityError: Plain text typing into a password field is strictly forbidden",
        ):
            await interactor.interact("type", "e0", "mysecret")

        with pytest.raises(
            ValueError,
            match="SecurityError: Plain text filling into a password field is strictly forbidden",
        ):
            await interactor.interact("fill", "e0", "mysecret")


@pytest.mark.asyncio
async def test_interact_fill_credential():
    page = AsyncMock(spec=Page)
    interactor = Interactor(
        page, {"e0": RefInfo(role="textbox", name="Password", nth=0)}
    )

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator"
    ) as mock_resolve:
        mock_loc = AsyncMock()
        mock_resolve.return_value = mock_loc

        with patch(
            "myrm_agent_harness.core.security.credential_vault.CredentialVault.get_password",
            return_value="secret123",
        ):
            res = await interactor.interact("fill_credential", "e0", "github-personal")
            assert "Filled credential 'github-personal'" in res
            mock_loc.fill.assert_called_once_with("secret123", timeout=10000)


@pytest.mark.asyncio
async def test_interact_fill_credential_totp():
    page = AsyncMock(spec=Page)
    interactor = Interactor(page, {"e0": RefInfo(role="textbox", name="Code", nth=0)})

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator"
    ) as mock_resolve:
        mock_loc = AsyncMock()
        mock_resolve.return_value = mock_loc

        with patch(
            "myrm_agent_harness.core.security.credential_vault.CredentialVault.get_totp_token",
            return_value="123456",
        ):
            res = await interactor.interact(
                "fill_credential", "e0", "github-personal-totp"
            )
            assert "Filled credential 'github-personal-totp'" in res
            mock_loc.fill.assert_called_once_with("123456", timeout=10000)


@pytest.mark.asyncio
async def test_interact_self_healing():
    page = AsyncMock(spec=Page)
    interactor = Interactor(page, {"e0": RefInfo(role="button", name="B", nth=0)})

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator"
    ) as mock_resolve:
        mock_loc = AsyncMock()
        mock_loc.wait_for.side_effect = Exception("timeout")
        mock_resolve.return_value = mock_loc

        with patch(
            "myrm_agent_harness.toolkits.browser.snapshot.self_healer.SelfHealer.heal",
            new_callable=AsyncMock,
        ) as mock_heal:
            healed_loc = AsyncMock()
            mock_heal.return_value = (healed_loc, "NewName", 0.5)

            with patch(
                "myrm_agent_harness.runtime.events.bus.get_event_bus"
            ) as mock_bus:
                mock_bus.return_value.publish = MagicMock()
                res = await interactor.interact("click", "e0")
                assert "Auto-Healed" in res
                assert "NewName" in res
                healed_loc.click.assert_called_once()
    page = AsyncMock(spec=Page)
    interactor = Interactor(page, {"e0": RefInfo(role="button", name="B", nth=0)})

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator"
    ) as mock_resolve:
        mock_loc = AsyncMock()
        mock_resolve.return_value = mock_loc

        with patch(
            "myrm_agent_harness.toolkits.browser.wait.wait_for_page_ready",
            side_effect=Exception("error"),
        ):
            res = await interactor.interact("click", "e0")
            assert "Clicked" in res


@pytest.mark.asyncio
async def test_interact_ref_not_found(interactor: Interactor) -> None:
    """Test interact with non-existent ref raises RefNotFoundError."""
    with pytest.raises(RefNotFoundError, match="Ref not found: e999"):
        await interactor.interact("click", "e999")


# =============================================================================
# Integration - multiple refs
# =============================================================================


@pytest.mark.asyncio
async def test_interactor_multiple_refs(mock_page: Any) -> None:
    """Test Interactor with multiple refs."""
    refs = {
        "e0": RefInfo("button", "Submit", None, {"x": 100, "y": 50}, "center-center"),
        "e1": RefInfo("textbox", "Email", None, {"x": 100, "y": 100}, "center-center"),
        "e2": RefInfo("checkbox", "Terms", None, {"x": 100, "y": 150}, "center-center"),
    }

    interactor = Interactor(mock_page, refs)

    mock_locator = AsyncMock()
    mock_locator.get_attribute.return_value = "text"

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        await interactor.interact("click", "e0")
        await interactor.interact("fill", "e1", "test@example.com")
        await interactor.interact("check", "e2")

        assert mock_locator.click.call_count == 1
        assert mock_locator.fill.call_count == 1
        assert mock_locator.check.call_count == 1


@pytest.mark.asyncio
async def test_interactor_update_refs_and_use(
    mock_page: Any, ref_info: RefInfo
) -> None:
    """Test updating refs and using new refs."""
    interactor = Interactor(mock_page, {})

    with pytest.raises(RefNotFoundError, match="Ref not found"):
        await interactor.interact("click", "e0")

    interactor.update_refs({"e0": ref_info})

    mock_locator = AsyncMock()
    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        result = await interactor.interact("click", "e0")
        assert "Clicked e0" in result


@pytest.mark.asyncio
async def test_interactor_unknown_action_coverage(
    mock_page: Any, ref_info: RefInfo
) -> None:
    """测试未知action的返回（覆盖line 178，理论死代码）"""
    from myrm_agent_harness.toolkits.browser.session import (
        interactor as interactor_module,
    )

    # 临时添加一个不在elif链中的action来触发line 178
    original_actions = interactor_module._VALID_ACTIONS
    interactor_module._VALID_ACTIONS = frozenset(original_actions | {"unknown_action"})

    try:
        test_interactor = Interactor(mock_page, {"e0": ref_info})

        mock_locator = AsyncMock()
        with patch(
            "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
            return_value=mock_locator,
        ):
            result = await test_interactor.interact("unknown_action", "e0", "")
            assert result == "Unknown action: unknown_action"
    finally:
        interactor_module._VALID_ACTIONS = original_actions


# =============================================================================
# Humanize primitives: overshoot / zero-delta guards (coverage)
# =============================================================================


@pytest.mark.asyncio
async def test_bezier_move_overshoot_correction(mock_page: Any) -> None:
    """bezier_move shoots past the target then corrects back when the chance hits."""
    from myrm_agent_harness.toolkits.browser.session.humanize import bezier_move

    cfg = HumanizeConfig()  # overshoot_chance=0.15 default
    with patch("random.random", return_value=0.05):  # < 0.15 → overshoot branch
        await bezier_move(mock_page, 0, 0, 200, 100, cfg)

    # steps = max(25, min(80, round(hypot(200,100)/8))) = 28 → 29 bezier moves
    # + 1 overshoot + 1 correction return = 31 total
    assert mock_page.mouse.move.call_count == 31
    last_x, last_y = mock_page.mouse.move.call_args_list[-1].args[:2]
    assert abs(last_x - 200) <= 5 and abs(last_y - 100) <= 5  # corrected back


@pytest.mark.asyncio
async def test_bezier_move_no_overshoot_when_chance_misses(mock_page: Any) -> None:
    """bezier_move without the overshoot hit ends exactly on the target."""
    from myrm_agent_harness.toolkits.browser.session.humanize import bezier_move

    cfg = HumanizeConfig()
    with patch("random.random", return_value=0.5):  # >= 0.15 → no overshoot
        await bezier_move(mock_page, 0, 0, 200, 100, cfg)

    assert mock_page.mouse.move.call_count == 29  # pure bezier path
    last_x, last_y = mock_page.mouse.move.call_args_list[-1].args[:2]
    assert last_x == 200 and last_y == 100  # lands exactly on target


@pytest.mark.asyncio
async def test_wheel_burst_zero_delta_noop(mock_page: Any) -> None:
    """wheel_burst with a zero delta emits no wheel events."""
    from myrm_agent_harness.toolkits.browser.session.humanize import wheel_burst

    mock_page.mouse.wheel = AsyncMock()
    await wheel_burst(mock_page, 0, HumanizeConfig())
    mock_page.mouse.wheel.assert_not_called()


@pytest.mark.asyncio
async def test_scroll_overshoot_correct_branch(mock_page: Any) -> None:
    """CAREFUL overshoot-and-correct fires when the chance check hits."""
    interactor = _careful_interactor(mock_page, {})
    mock_page.mouse.wheel = AsyncMock()

    with patch("random.random", return_value=0.05):  # < scroll_overshoot_chance=0.1
        await interactor._scroll_overshoot_correct(1)

    # overshoot burst + 1-2 correction bursts each emit wheel events
    assert mock_page.mouse.wheel.call_count >= 2


@pytest.mark.asyncio
async def test_interact_fill_credential_vault_error(mock_page: Any) -> None:
    """Vault lookup failure surfaces as a clear ValueError."""
    interactor = Interactor(
        mock_page, {"e0": RefInfo(role="textbox", name="Code", nth=0)}
    )

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator"
    ) as mock_resolve:
        mock_resolve.return_value = AsyncMock()
        with (
            patch(
                "myrm_agent_harness.core.security.credential_vault.CredentialVault.get_password",
                side_effect=Exception("vault locked"),
            ),
            pytest.raises(ValueError, match="Failed to retrieve credential"),
        ):
            await interactor.interact("fill_credential", "e0", "github-personal")


@pytest.mark.asyncio
async def test_interact_dialog_check_failure_falls_back(
    mock_page: Any, ref_info: RefInfo
) -> None:
    """Dialog detection failure degrades to the normal error path (no hint)."""
    interactor = Interactor(mock_page, {"e0": ref_info})
    locator = AsyncMock()
    locator.click.side_effect = Exception("Timeout 30000 ms exceeded")
    with (
        patch(
            "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
            return_value=locator,
        ),
        patch(
            "myrm_agent_harness.toolkits.computer_use.session.create_computer_session",
            side_effect=Exception("no backend"),
        ),
        patch(
            "myrm_agent_harness.toolkits.browser.session.interactor.logger.warning"
        ) as mock_warn,
        pytest.raises(Exception, match="Timeout"),
    ):
        await interactor.interact("click", "e0", "")

    # Falls through to the "no OS dialog detected" branch, still warns, then re-raises.
    assert mock_warn.call_count == 1


# =============================================================================
# Additional coverage: remaining defensive branches
# =============================================================================


@pytest.mark.asyncio
async def test_bezier_move_identical_points_noop(mock_page: Any) -> None:
    """bezier_move with start == end emits no mouse events."""
    from myrm_agent_harness.toolkits.browser.session.humanize import bezier_move

    mock_page.mouse.move = AsyncMock()
    await bezier_move(mock_page, 100, 100, 100, 100, HumanizeConfig())
    mock_page.mouse.move.assert_not_called()


def test_scroll_burst_break_ms_fast_returns_zero() -> None:
    """FAST mode never pauses between scroll notches."""
    from myrm_agent_harness.toolkits.browser.session.humanize import (
        scroll_burst_break_ms,
    )

    cfg = HumanizeConfig.from_mode(HumanizeMode.FAST)
    assert scroll_burst_break_ms(cfg, in_burst=True, phase_changed=True) == 0


@pytest.mark.asyncio
async def test_scroll_cursor_target_unmeasurable_uses_viewport_center(
    mock_page: Any, refs_map: dict[str, RefInfo]
) -> None:
    """A hidden target makes the wheel cursor fall back to the viewport center."""
    interactor = _careful_interactor(mock_page, refs_map)
    locator = AsyncMock()
    locator.bounding_box.return_value = None

    x, y = await interactor._scroll_cursor_target(locator)

    assert (x, y) == (640.0, 360.0)


@pytest.mark.asyncio
async def test_scroll_cursor_target_measure_error_uses_viewport_center(
    mock_page: Any, refs_map: dict[str, RefInfo]
) -> None:
    """A bounding-box error degrades to the viewport center."""
    interactor = _careful_interactor(mock_page, refs_map)
    locator = AsyncMock()
    locator.bounding_box.side_effect = Exception("Target closed")

    x, y = await interactor._scroll_cursor_target(locator)

    assert (x, y) == (640.0, 360.0)


@pytest.mark.asyncio
async def test_target_box_wait_failure_returns_none(
    mock_page: Any, refs_map: dict[str, RefInfo]
) -> None:
    """wait_for failure yields None so callers degrade gracefully."""
    interactor = _careful_interactor(mock_page, refs_map)
    locator = AsyncMock()
    locator.wait_for.side_effect = Exception("timeout")

    assert await interactor._target_box(locator) is None


@pytest.mark.asyncio
async def test_ensure_target_in_view_box_disappears_mid_scroll(
    mock_page: Any, refs_map: dict[str, RefInfo]
) -> None:
    """The target vanishes mid-scroll: report the scroll that already happened."""
    interactor = _careful_interactor(mock_page, refs_map)
    locator = AsyncMock()
    off_zone = {"x": 100, "y": 1800, "width": 200, "height": 100}
    # first loop re-check box (below) + probe (invisible → container wheel),
    # then loop re-check box → None → break
    locator.bounding_box.side_effect = [off_zone, None]
    locator.evaluate.return_value = _probe(
        visible=False, y=1800, container=_doc_container(1490)
    )
    mock_page.mouse.wheel = AsyncMock()

    with (
        patch.object(interactor, "_scroll_deliver", new=AsyncMock()),
        patch("random.random", return_value=0.5),
    ):
        moved = await interactor._ensure_target_in_view(locator)

    assert moved is True  # one wheel delivery already happened


@pytest.mark.asyncio
async def test_ensure_target_in_view_delta_zero_breaks(
    mock_page: Any, refs_map: dict[str, RefInfo]
) -> None:
    """A target within a fraction of the band: delta rounds to zero, loop stops."""
    interactor = _careful_interactor(mock_page, refs_map)
    locator = AsyncMock()
    # vh=720 → zone_hi=504. cy = 454.4 + 50 = 504.4 → delta = round(0.4) = 0
    locator.bounding_box.return_value = {
        "x": 100,
        "y": 454.4,
        "width": 200,
        "height": 100,
    }
    locator.evaluate.return_value = _probe(
        y=454.4,
        container={
            "left": 0,
            "top": 0,
            "width": 1280,
            "height": 720,
            "is_doc": True,
            "delta": 0,
        },
    )
    mock_page.mouse.wheel = AsyncMock()

    assert await interactor._ensure_target_in_view(locator) is False


@pytest.mark.asyncio
async def test_scroll_noop_reason_smooth_scroll_settles(mock_page: Any) -> None:
    """Smooth scroll: the container moves after the settle delay, no reason given."""
    interactor = Interactor(mock_page, {})
    state_a = {"top": 0.0, "height": 2000.0, "client": 720.0}
    state_b = {"top": 100.0, "height": 2000.0, "client": 720.0}
    states = iter([state_a, state_b])

    async def mock_evaluate(expr: str, arg: Any = None) -> Any:
        if "innerHeight" in expr:
            return 800
        if "elementFromPoint" in expr:
            return next(states)
        return 0

    mock_page.evaluate = AsyncMock(side_effect=mock_evaluate)
    mock_page.mouse.wheel = AsyncMock()

    reason = await interactor._scroll_noop_reason(400, 300, state_a, 300)

    assert reason == ""


@pytest.mark.asyncio
async def test_scroll_deliver_zero_delta_noop(mock_page: Any) -> None:
    """Zero delta emits no wheel events in any mode."""
    for mode in (HumanizeMode.FAST, HumanizeMode.DEFAULT, HumanizeMode.CAREFUL):
        interactor = Interactor(mock_page, {}, humanize=HumanizeConfig.from_mode(mode))
        mock_page.mouse.wheel = AsyncMock()
        await interactor._scroll_deliver(0)
        mock_page.mouse.wheel.assert_not_called()


@pytest.mark.asyncio
async def test_bezier_move_to_initializes_mouse_position(
    mock_page: Any, refs_map: dict[str, RefInfo]
) -> None:
    """A first Bézier move seeds the mouse from the viewport center."""
    interactor = _careful_interactor(mock_page, refs_map)
    interactor._mouse_x = 0.0
    interactor._mouse_y = 0.0
    locator = AsyncMock()
    locator.bounding_box.return_value = {"x": 400, "y": 300, "width": 100, "height": 60}

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor_click_mixin.bezier_move",
        new_callable=AsyncMock,
    ) as mock_bezier:
        assert await interactor._bezier_move_to(locator) is True

    start_x, start_y = mock_bezier.await_args.args[1], mock_bezier.await_args.args[2]
    assert (start_x, start_y) == (640.0, 360.0)  # seeded from the viewport center


@pytest.mark.asyncio
async def test_ensure_target_in_view_probe_measure_failure_breaks(
    mock_page: Any, refs_map: dict[str, RefInfo]
) -> None:
    """A rendered-state probe failure yields None and stops the loop silently."""
    interactor = _careful_interactor(mock_page, refs_map)
    locator = AsyncMock()
    locator.bounding_box.return_value = {"x": 100, "y": 600, "width": 200, "height": 100}
    locator.evaluate.side_effect = Exception("frame navigated")

    assert await interactor._ensure_target_in_view(locator) is False


@pytest.mark.asyncio
async def test_ensure_target_in_view_scrolls_visible_target_into_band(
    mock_page: Any, refs_map: dict[str, RefInfo]
) -> None:
    """A top-frame target outside the center band is wheeled toward the band."""
    interactor = _careful_interactor(mock_page, refs_map)
    locator = AsyncMock()
    # vh=720 → band [216, 504]. First pass: cy=600 (> 504) → wheel; second: cy=400 → stop.
    locator.bounding_box.side_effect = [
        {"x": 100, "y": 550, "width": 200, "height": 100},
        {"x": 100, "y": 350, "width": 200, "height": 100},
    ]
    locator.evaluate.side_effect = [
        _probe(y=550),  # visible, is_top, container=None → band scroll
        _probe(y=350),
    ]
    mock_page.mouse.wheel = AsyncMock()

    with (
        patch.object(interactor, "_scroll_move_cursor", new=AsyncMock()) as mock_move,
        patch.object(interactor, "_scroll_deliver", new=AsyncMock()) as mock_deliver,
    ):
        moved = await interactor._ensure_target_in_view(locator)

    assert moved is True
    mock_move.assert_awaited_once()
    mock_deliver.assert_awaited_once()
