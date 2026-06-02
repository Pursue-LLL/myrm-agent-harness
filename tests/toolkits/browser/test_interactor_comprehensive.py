"""Comprehensive tests for Interactor (100% coverage)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.exceptions import RefNotFoundError
from myrm_agent_harness.toolkits.browser.session.interactor import Interactor
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
        mock_locator.click.assert_called_once_with(timeout=10_000)


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
        mock_locator.dblclick.assert_called_once_with(timeout=10_000)


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
        mock_locator.type.assert_called_once_with("Hello World", timeout=10_000)


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
    with pytest.raises(ValueError, match="Invalid action: invalid_action"):
        await interactor.interact("invalid_action", "e0")


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
