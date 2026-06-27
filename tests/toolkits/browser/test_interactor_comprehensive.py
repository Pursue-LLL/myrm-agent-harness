"""Comprehensive tests for Interactor (100% coverage)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.exceptions import RefNotFoundError
from myrm_agent_harness.toolkits.browser.session.interactor import (
    Interactor,
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
    return page


@pytest.fixture
def interactor(mock_page: Any, refs_map: dict[str, RefInfo]) -> Interactor:
    """Create Interactor with mocked page and refs."""
    return Interactor(mock_page, refs_map)


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

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
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

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
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

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
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

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
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

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
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

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
        result = await interactor.interact("hover", "e0")

        assert result == "Hovered over e0"
        mock_locator.hover.assert_called_once_with(timeout=10_000)


@pytest.mark.asyncio
async def test_interact_hover_bezier_success(mock_page: Any, refs_map: dict[str, RefInfo]) -> None:
    """Test hover in CAREFUL mode uses Bézier trajectory when bounding_box succeeds."""
    from myrm_agent_harness.toolkits.browser.pool.config import HumanizeConfig, HumanizeMode

    cfg = HumanizeConfig.from_mode(HumanizeMode.CAREFUL)
    interactor = Interactor(mock_page, refs_map, humanize=cfg)

    mock_locator = AsyncMock()
    mock_locator.bounding_box = AsyncMock(return_value={"x": 100, "y": 50, "width": 80, "height": 30})
    mock_page.mouse = MagicMock()
    mock_page.mouse.move = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.viewport_size = {"width": 800, "height": 600}

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
        result = await interactor.interact("hover", "e0")

    assert result == "Hovered over e0"
    mock_locator.hover.assert_not_called()
    assert mock_page.mouse.move.call_count >= 1


@pytest.mark.asyncio
async def test_interact_hover_bezier_fallback(mock_page: Any, refs_map: dict[str, RefInfo]) -> None:
    """Test hover in CAREFUL mode falls back to locator.hover() when bounding_box returns None."""
    from myrm_agent_harness.toolkits.browser.pool.config import HumanizeConfig, HumanizeMode

    cfg = HumanizeConfig.from_mode(HumanizeMode.CAREFUL)
    interactor = Interactor(mock_page, refs_map, humanize=cfg)

    mock_locator = AsyncMock()
    mock_locator.bounding_box = AsyncMock(return_value=None)

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
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

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
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

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
        result = await interactor.interact("select", "e0", "option1")

        assert result == "Selected 'option1' in e0"
        mock_locator.select_option.assert_called_once_with("option1", timeout=10_000)


# =============================================================================
# Action: scroll
# =============================================================================


@pytest.mark.asyncio
async def test_interact_scroll_positive(interactor: Interactor, mock_page: Any) -> None:
    """Test scroll action with positive delta."""
    mock_locator = AsyncMock()

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
        result = await interactor.interact("scroll", "e0", "100")

        assert result == "Scrolled 100px"
        mock_locator.scroll_into_view_if_needed.assert_called_once_with(timeout=10_000)
        mock_page.evaluate.assert_called_once_with("window.scrollBy(0, 100)")


@pytest.mark.asyncio
async def test_interact_scroll_negative(interactor: Interactor, mock_page: Any) -> None:
    """Test scroll action with negative delta."""
    mock_locator = AsyncMock()

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
        result = await interactor.interact("scroll", "e0", "-50")

        assert result == "Scrolled -50px"
        mock_locator.scroll_into_view_if_needed.assert_called_once_with(timeout=10_000)
        mock_page.evaluate.assert_called_once_with("window.scrollBy(0, -50)")


@pytest.mark.asyncio
async def test_interact_scroll_invalid_text(interactor: Interactor) -> None:
    """Test scroll with invalid text raises ValueError."""
    mock_locator = AsyncMock()

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
        with pytest.raises(ValueError, match="Scroll requires numeric text"):
            await interactor.interact("scroll", "e0", "not_a_number")


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


# =============================================================================
# Action: scroll_to_bottom
# =============================================================================


@pytest.mark.asyncio
async def test_scroll_to_bottom_reaches_bottom(interactor: Interactor, mock_page: Any) -> None:
    """scroll_to_bottom stops when scrollHeight stabilizes."""
    mock_locator = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()

    heights = [1000, 1500, 2000, 2000, 2000, 2000]
    call_idx = {"i": 0}

    async def mock_evaluate(expr: str) -> int:
        if "scrollHeight" in expr:
            idx = min(call_idx["i"], len(heights) - 1)
            call_idx["i"] += 1
            return heights[idx]
        if "innerHeight" in expr:
            return 800
        return 0

    mock_page.evaluate = AsyncMock(side_effect=mock_evaluate)

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
        result = await interactor.interact("scroll_to_bottom", "e0", "")

    assert "completed" in result
    assert "steps" in result.lower() or "Scrolled" in result


@pytest.mark.asyncio
async def test_scroll_to_bottom_max_steps_reached(interactor: Interactor, mock_page: Any) -> None:
    """scroll_to_bottom respects max_steps when page keeps growing."""
    mock_locator = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()

    height_counter = {"h": 1000}

    async def mock_evaluate(expr: str) -> int:
        if "scrollHeight" in expr:
            height_counter["h"] += 500
            return height_counter["h"]
        if "innerHeight" in expr:
            return 800
        return 0

    mock_page.evaluate = AsyncMock(side_effect=mock_evaluate)

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
        result = await interactor.interact("scroll_to_bottom", "e0", "max_steps=3")

    assert "max_reached" in result
    assert "3 steps" in result


@pytest.mark.asyncio
async def test_scroll_to_bottom_with_custom_params(interactor: Interactor, mock_page: Any) -> None:
    """scroll_to_bottom accepts custom delay_ms and stable_count."""
    mock_locator = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()

    heights = [1000, 1000, 1000]
    call_idx = {"i": 0}

    async def mock_evaluate(expr: str) -> int:
        if "scrollHeight" in expr:
            idx = min(call_idx["i"], len(heights) - 1)
            call_idx["i"] += 1
            return heights[idx]
        if "innerHeight" in expr:
            return 800
        return 0

    mock_page.evaluate = AsyncMock(side_effect=mock_evaluate)

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
        result = await interactor.interact(
            "scroll_to_bottom", "e0", "delay_ms=200,stable_count=2"
        )

    assert "completed" in result
    mock_page.wait_for_timeout.assert_called_with(200)


@pytest.mark.asyncio
async def test_scroll_to_bottom_single_step_already_at_bottom(
    interactor: Interactor, mock_page: Any
) -> None:
    """Page already at bottom returns completed after stable_count checks."""
    mock_locator = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()

    async def mock_evaluate(expr: str) -> int:
        if "scrollHeight" in expr:
            return 500
        if "innerHeight" in expr:
            return 800
        return 0

    mock_page.evaluate = AsyncMock(side_effect=mock_evaluate)

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
        result = await interactor.interact("scroll_to_bottom", "e0", "")

    assert "completed" in result


@pytest.mark.asyncio
async def test_scroll_to_bottom_viewport_zero_fallback(
    interactor: Interactor, mock_page: Any
) -> None:
    """viewport_h <= 0 falls back to 800."""
    mock_locator = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()

    heights = [1000, 1000, 1000, 1000]
    call_idx = {"i": 0}

    async def mock_evaluate(expr: str) -> int:
        if "scrollHeight" in expr:
            idx = min(call_idx["i"], len(heights) - 1)
            call_idx["i"] += 1
            return heights[idx]
        if "innerHeight" in expr:
            return 0  # viewport returns 0
        if "scrollBy" in expr:
            return 0
        return 0

    mock_page.evaluate = AsyncMock(side_effect=mock_evaluate)

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
        result = await interactor.interact("scroll_to_bottom", "e0", "stable_count=2")

    assert "completed" in result


@pytest.mark.asyncio
async def test_scroll_to_bottom_height_output_format(
    interactor: Interactor, mock_page: Any
) -> None:
    """Return string contains steps, elapsed, height range, and status."""
    mock_locator = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()

    heights = [1000, 2000, 2000, 2000, 2000]
    call_idx = {"i": 0}

    async def mock_evaluate(expr: str) -> int:
        if "scrollHeight" in expr:
            idx = min(call_idx["i"], len(heights) - 1)
            call_idx["i"] += 1
            return heights[idx]
        if "innerHeight" in expr:
            return 800
        return 0

    mock_page.evaluate = AsyncMock(side_effect=mock_evaluate)

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
        result = await interactor.interact("scroll_to_bottom", "e0", "")

    assert "Scrolled" in result
    assert "steps" in result
    assert "Height:" in result
    assert "Status:" in result
    assert "completed" in result


# =============================================================================
# Action: upload_file
# =============================================================================


@pytest.mark.asyncio
async def test_interact_upload_file(interactor: Interactor) -> None:
    """Test upload_file action."""
    mock_locator = AsyncMock()

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
        result = await interactor.interact("upload_file", "e0", "/tmp/file.txt")

        assert result == "Uploaded file to e0: /tmp/file.txt"
        mock_locator.set_input_files.assert_called_once_with("/tmp/file.txt", timeout=10_000)


# =============================================================================
# Action: drag
# =============================================================================


@pytest.mark.asyncio
async def test_interact_drag_success(interactor: Interactor, mock_page: Any) -> None:
    """Test drag action with valid coordinates."""
    mock_locator = AsyncMock()
    body_locator = MagicMock()
    mock_page.locator.return_value = body_locator

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
        result = await interactor.interact("drag", "e0", "200,150")

        assert result == "Dragged e0 to (200, 150)"
        mock_locator.drag_to.assert_called_once_with(body_locator, target_position={"x": 200, "y": 150})


@pytest.mark.asyncio
async def test_interact_drag_invalid_format(interactor: Interactor) -> None:
    """Test drag with invalid text format."""
    mock_locator = AsyncMock()

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
        with pytest.raises(ValueError, match="Drag requires 'x,y' text"):
            await interactor.interact("drag", "e0", "invalid")


@pytest.mark.asyncio
async def test_interact_drag_non_numeric(interactor: Interactor) -> None:
    """Test drag with non-numeric coordinates."""
    mock_locator = AsyncMock()

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
        with pytest.raises(ValueError, match="Drag requires numeric 'x,y'"):
            await interactor.interact("drag", "e0", "abc,def")


# =============================================================================
# Action: check
# =============================================================================


@pytest.mark.asyncio
async def test_interact_check(interactor: Interactor) -> None:
    """Test check action."""
    mock_locator = AsyncMock()

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
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

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
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
    from myrm_agent_harness.toolkits.browser.session.interactor import RefNotFoundMetrics
    metrics = RefNotFoundMetrics()
    assert metrics.failure_rate == 0.0
    assert metrics.recent_failure_rate == 0.0
    assert metrics.top_failed_refs == []
    assert metrics.top_failed_actions == []
    d = metrics.to_dict()
    assert d["total_failures"] == 0

def test_metrics_caching():
    from myrm_agent_harness.toolkits.browser.session.interactor import RefNotFoundMetrics
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
    interactor.update_refs({"e1": RefInfo(role="link", name="L", nth=0)}, last_snapshot_url="http://new")
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
    from myrm_agent_harness.toolkits.browser.session.interactor import RefNotFoundMetrics
    assert isinstance(interactor.metrics, RefNotFoundMetrics)

def test_log_metrics_if_needed():
    page = AsyncMock(spec=Page)
    interactor = Interactor(page, {})
    interactor._metrics.total_interactions = 100
    interactor._metrics.total_failures = 1
    with patch("myrm_agent_harness.toolkits.browser.session.interactor.logger.info") as mock_info:
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

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator") as mock_resolve:
        mock_loc = AsyncMock()
        mock_loc.click.side_effect = Exception("TargetClosedError")
        mock_resolve.return_value = mock_loc

        with patch("myrm_agent_harness.toolkits.computer_use.session.create_computer_session") as mock_create:
            mock_cu = AsyncMock()
            mock_cu.backend.has_blocking_dialog.return_value = True
            mock_create.return_value = mock_cu

            res = await interactor.interact("click", "e0")
            assert "CRITICAL WARNING" in res

@pytest.mark.asyncio
async def test_interact_exception_no_dialog():
    page = AsyncMock(spec=Page)
    interactor = Interactor(page, {"e0": RefInfo(role="button", name="B", nth=0)})

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator") as mock_resolve:
        mock_loc = AsyncMock()
        mock_loc.click.side_effect = Exception("TargetClosedError")
        mock_resolve.return_value = mock_loc

        with patch("myrm_agent_harness.toolkits.computer_use.session.create_computer_session") as mock_create:
            mock_cu = AsyncMock()
            mock_cu.backend.has_blocking_dialog.return_value = False
            mock_create.return_value = mock_cu

            with pytest.raises(Exception, match="TargetClosedError"):
                await interactor.interact("click", "e0")


@pytest.mark.asyncio
async def test_interact_type_exception():
    page = AsyncMock(spec=Page)
    interactor = Interactor(page, {"e0": RefInfo(role="button", name="B", nth=0)})

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator") as mock_resolve:
        mock_loc = AsyncMock()
        mock_loc.get_attribute.side_effect = Exception("error")
        mock_resolve.return_value = mock_loc

        res = await interactor.interact("type", "e0", "test")
        assert "Typed 'test'" in res


@pytest.mark.asyncio
async def test_interact_fill_exception():
    page = AsyncMock(spec=Page)
    interactor = Interactor(page, {"e0": RefInfo(role="button", name="B", nth=0)})

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator") as mock_resolve:
        mock_loc = AsyncMock()
        mock_loc.get_attribute.side_effect = Exception("error")
        mock_resolve.return_value = mock_loc

        res = await interactor.interact("fill", "e0", "test")
        assert "Filled" in res


@pytest.mark.asyncio
async def test_interact_password_blocked():
    page = AsyncMock(spec=Page)
    interactor = Interactor(page, {"e0": RefInfo(role="textbox", name="Password", nth=0)})

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator") as mock_resolve:
        mock_loc = AsyncMock()
        mock_loc.get_attribute.return_value = "password"
        mock_resolve.return_value = mock_loc

        with pytest.raises(ValueError, match="SecurityError: Plain text typing into a password field is strictly forbidden"):
            await interactor.interact("type", "e0", "mysecret")

        with pytest.raises(ValueError, match="SecurityError: Plain text filling into a password field is strictly forbidden"):
            await interactor.interact("fill", "e0", "mysecret")


@pytest.mark.asyncio
async def test_interact_fill_credential():
    page = AsyncMock(spec=Page)
    interactor = Interactor(page, {"e0": RefInfo(role="textbox", name="Password", nth=0)})

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator") as mock_resolve:
        mock_loc = AsyncMock()
        mock_resolve.return_value = mock_loc

        with patch("myrm_agent_harness.toolkits.security.credential_vault.CredentialVault.get_password", return_value="secret123"):
            res = await interactor.interact("fill_credential", "e0", "github-personal")
            assert "Filled credential 'github-personal'" in res
            mock_loc.fill.assert_called_once_with("secret123", timeout=10000)


@pytest.mark.asyncio
async def test_interact_fill_credential_totp():
    page = AsyncMock(spec=Page)
    interactor = Interactor(page, {"e0": RefInfo(role="textbox", name="Code", nth=0)})

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator") as mock_resolve:
        mock_loc = AsyncMock()
        mock_resolve.return_value = mock_loc

        with patch("myrm_agent_harness.toolkits.security.credential_vault.CredentialVault.get_totp_token", return_value="123456"):
            res = await interactor.interact("fill_credential", "e0", "github-personal-totp")
            assert "Filled credential 'github-personal-totp'" in res
            mock_loc.fill.assert_called_once_with("123456", timeout=10000)


@pytest.mark.asyncio
async def test_interact_self_healing():
    page = AsyncMock(spec=Page)
    interactor = Interactor(page, {"e0": RefInfo(role="button", name="B", nth=0)})

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator") as mock_resolve:
        mock_loc = AsyncMock()
        mock_loc.wait_for.side_effect = Exception("timeout")
        mock_resolve.return_value = mock_loc

        with patch("myrm_agent_harness.toolkits.browser.snapshot.self_healer.SelfHealer.heal", new_callable=AsyncMock) as mock_heal:
            healed_loc = AsyncMock()
            mock_heal.return_value = (healed_loc, "NewName", 0.5)

            with patch("myrm_agent_harness.runtime.events.bus.get_event_bus") as mock_bus:
                mock_bus.return_value.publish = MagicMock()
                res = await interactor.interact("click", "e0")
                assert "Auto-Healed" in res
                assert "NewName" in res
                healed_loc.click.assert_called_once()
    page = AsyncMock(spec=Page)
    interactor = Interactor(page, {"e0": RefInfo(role="button", name="B", nth=0)})

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator") as mock_resolve:
        mock_loc = AsyncMock()
        mock_resolve.return_value = mock_loc

        with patch("myrm_agent_harness.toolkits.browser.wait_strategies.wait_for_page_ready", side_effect=Exception("error")):
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

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
        await interactor.interact("click", "e0")
        await interactor.interact("fill", "e1", "test@example.com")
        await interactor.interact("check", "e2")

        assert mock_locator.click.call_count == 1
        assert mock_locator.fill.call_count == 1
        assert mock_locator.check.call_count == 1


@pytest.mark.asyncio
async def test_interactor_update_refs_and_use(mock_page: Any, ref_info: RefInfo) -> None:
    """Test updating refs and using new refs."""
    interactor = Interactor(mock_page, {})

    with pytest.raises(RefNotFoundError, match="Ref not found"):
        await interactor.interact("click", "e0")

    interactor.update_refs({"e0": ref_info})

    mock_locator = AsyncMock()
    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
        result = await interactor.interact("click", "e0")
        assert "Clicked e0" in result


@pytest.mark.asyncio
async def test_interactor_unknown_action_coverage(mock_page: Any, ref_info: RefInfo) -> None:
    """测试未知action的返回（覆盖line 178，理论死代码）"""
    from myrm_agent_harness.toolkits.browser.session import interactor as interactor_module

    # 临时添加一个不在elif链中的action来触发line 178
    original_actions = interactor_module._VALID_ACTIONS
    interactor_module._VALID_ACTIONS = frozenset(original_actions | {"unknown_action"})

    try:
        test_interactor = Interactor(mock_page, {"e0": ref_info})

        mock_locator = AsyncMock()
        with patch(
            "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator
        ):
            result = await test_interactor.interact("unknown_action", "e0", "")
            assert result == "Unknown action: unknown_action"
    finally:
        interactor_module._VALID_ACTIONS = original_actions
