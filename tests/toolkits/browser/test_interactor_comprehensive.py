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
