"""Comprehensive tests for Interactor (100% coverage)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.exceptions import RefNotFoundError
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

    mock_locator = AsyncMock()
    mock_locator.bounding_box = AsyncMock(
        return_value={"x": 100, "y": 50, "width": 80, "height": 30}
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
    mock_page.mouse.wheel = AsyncMock()

    moved = await interactor._ensure_target_in_view(locator)

    assert moved is False
    mock_page.mouse.wheel.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_target_in_view_scrolls_below_target(
    mock_page: Any, refs_map: dict[str, RefInfo]
) -> None:
    """A target below the band is wheeled toward it (humanized notches)."""
    interactor = _careful_interactor(mock_page, refs_map)
    locator = AsyncMock()
    locator.bounding_box.return_value = {
        "x": 100,
        "y": 1800,
        "width": 200,
        "height": 100,
    }  # cy = 1850 > zone_hi = 504
    mock_page.mouse.wheel = AsyncMock()

    with patch("random.random", return_value=0.5):  # no overshoot branch
        moved = await interactor._ensure_target_in_view(locator)

    assert moved is True
    assert mock_page.mouse.wheel.call_count >= 1


@pytest.mark.asyncio
async def test_ensure_target_in_view_scrolls_above_target(
    mock_page: Any, refs_map: dict[str, RefInfo]
) -> None:
    """A target above the band is wheeled up (negative delta)."""
    interactor = _careful_interactor(mock_page, refs_map)
    locator = AsyncMock()
    locator.bounding_box.return_value = {
        "x": 100,
        "y": -800,
        "width": 200,
        "height": 100,
    }  # cy = -750 < zone_lo = 216
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
    """Per-step re-measure breaks the loop as soon as the target enters the zone."""
    interactor = _careful_interactor(mock_page, refs_map)
    locator = AsyncMock()
    # Read order: target-box check (below), cursor-target clamp, loop re-check
    # (still below -> one deliver), loop re-check (inside -> break).
    locator.bounding_box.side_effect = [
        {"x": 100, "y": 1800, "width": 200, "height": 100},
        {"x": 100, "y": 1800, "width": 200, "height": 100},
        {"x": 100, "y": 1800, "width": 200, "height": 100},
        {"x": 100, "y": 300, "width": 200, "height": 100},
        {"x": 100, "y": 300, "width": 200, "height": 100},
    ]
    mock_page.mouse.wheel = AsyncMock()

    with (
        patch.object(interactor, "_scroll_deliver", new=AsyncMock()) as mock_deliver,
        patch("random.random", return_value=0.5),
    ):
        moved = await interactor._ensure_target_in_view(locator)

    assert moved is True
    mock_deliver.assert_awaited_once()  # re-measure breaks the loop right after


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
    mock_page.mouse.wheel = AsyncMock(side_effect=Exception("Target closed"))

    moved = await interactor._ensure_target_in_view(locator)

    assert moved is False


@pytest.mark.asyncio
async def test_interact_click_careful_pre_scrolls(mock_page: Any) -> None:
    """CAREFUL click on an off-band target humanized-wheels it into view first."""
    refs = {
        "e0": RefInfo(
            role="button", name="Click Me", nth=None, bbox={"x": 100, "y": 50}, position="center-center"
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
            role="button", name="Click Me", nth=None, bbox={"x": 100, "y": 50}, position="center-center"
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
