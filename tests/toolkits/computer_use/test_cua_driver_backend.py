"""Tests for CuaDriverBackend — proxy pattern and fallback logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.computer_use.backends.cua_driver import (
    CuaDriverBackend,
    _extract_result,
    is_cua_driver_available,
)
from myrm_agent_harness.toolkits.computer_use.types import (
    ActionResult,
    PermissionStatus,
    ScreenContext,
    ScreenInfo,
    WindowTextResult,
)


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def mock_fallback():
    """Create a mock fallback backend with all ComputerBackend methods."""
    fb = MagicMock()
    fb.screenshot = AsyncMock(return_value=b"png-bytes")
    fb.click = AsyncMock(return_value=ActionResult(success=True))
    fb.type_text = AsyncMock(return_value=ActionResult(success=True))
    fb.type_credential = AsyncMock(return_value=ActionResult(success=True))
    fb.key = AsyncMock(return_value=ActionResult(success=True))
    fb.mouse_move = AsyncMock(return_value=ActionResult(success=True))
    fb.scroll = AsyncMock(return_value=ActionResult(success=True))
    fb.drag = AsyncMock(return_value=ActionResult(success=True))
    fb.wait = AsyncMock(return_value=ActionResult(success=True))
    fb.screen_info = MagicMock(return_value=ScreenInfo(width=1920, height=1080, dpi_scale=1.0))
    fb.screen_context = MagicMock(return_value=ScreenContext(active_window="Test", mouse_x=0, mouse_y=0))
    fb.window_text = AsyncMock(return_value=WindowTextResult(success=True))
    fb.has_blocking_dialog = AsyncMock(return_value=False)
    fb.is_browser_active = AsyncMock(return_value=False)
    fb.check_permissions = AsyncMock(return_value=PermissionStatus(accessibility=True, screen_recording=True))
    return fb


@pytest.fixture
def backend(mock_fallback: MagicMock) -> CuaDriverBackend:
    return CuaDriverBackend(fallback=mock_fallback)


def _make_mcp_result(data: str = "", is_error: bool = False) -> dict:
    return {"data": data, "images": [], "structuredContent": None, "isError": is_error}


def _stub_resolve(backend: CuaDriverBackend, pid: int = 12345) -> None:
    """Patch _resolve_target to return a fixed PID without MCP call."""
    backend._resolve_target = AsyncMock(return_value=pid)  # type: ignore[method-assign]


# ── Delegation tests: non-input ops always go to fallback ─────────

@pytest.mark.asyncio
async def test_screenshot_delegates_to_fallback(backend: CuaDriverBackend, mock_fallback: MagicMock):
    result = await backend.screenshot()
    assert result == b"png-bytes"
    mock_fallback.screenshot.assert_awaited_once()


def test_screen_info_delegates_to_fallback(backend: CuaDriverBackend, mock_fallback: MagicMock):
    info = backend.screen_info()
    assert info.width == 1920
    mock_fallback.screen_info.assert_called_once()


def test_screen_context_delegates_to_fallback(backend: CuaDriverBackend, mock_fallback: MagicMock):
    ctx = backend.screen_context()
    assert ctx.active_window == "Test"
    mock_fallback.screen_context.assert_called_once()


@pytest.mark.asyncio
async def test_window_text_delegates_to_fallback(backend: CuaDriverBackend, mock_fallback: MagicMock):
    result = await backend.window_text()
    assert result.success is True
    mock_fallback.window_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_wait_delegates_to_fallback(backend: CuaDriverBackend, mock_fallback: MagicMock):
    result = await backend.wait(1.0)
    assert result.success is True
    mock_fallback.wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_permissions_delegates(backend: CuaDriverBackend, mock_fallback: MagicMock):
    result = await backend.check_permissions()
    assert result.accessibility is True
    mock_fallback.check_permissions.assert_awaited_once()


# ── Fallback on MCP failure ───────────────────────────────────────

@pytest.mark.asyncio
async def test_click_falls_back_on_mcp_failure(backend: CuaDriverBackend, mock_fallback: MagicMock):
    """When cua-driver session fails, click should fall back to pyautogui."""
    backend._mcp._started = True
    backend._mcp.call_tool = AsyncMock(side_effect=RuntimeError("connection failed"))
    _stub_resolve(backend)

    result = await backend.click(100, 200)
    assert result.success is True
    mock_fallback.click.assert_awaited_once_with(100, 200, "left", 1, modifiers=None)


@pytest.mark.asyncio
async def test_type_text_falls_back_on_mcp_failure(backend: CuaDriverBackend, mock_fallback: MagicMock):
    backend._mcp._started = True
    backend._mcp.call_tool = AsyncMock(side_effect=RuntimeError("connection failed"))
    _stub_resolve(backend)

    result = await backend.type_text("hello")
    assert result.success is True
    mock_fallback.type_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_key_falls_back_on_mcp_failure(backend: CuaDriverBackend, mock_fallback: MagicMock):
    backend._mcp._started = True
    backend._mcp.call_tool = AsyncMock(side_effect=RuntimeError("connection failed"))
    _stub_resolve(backend)

    result = await backend.key("Return")
    assert result.success is True
    mock_fallback.key.assert_awaited_once()


@pytest.mark.asyncio
async def test_scroll_falls_back_on_mcp_failure(backend: CuaDriverBackend, mock_fallback: MagicMock):
    backend._mcp._started = True
    backend._mcp.call_tool = AsyncMock(side_effect=RuntimeError("connection failed"))
    _stub_resolve(backend)

    result = await backend.scroll(100, 200, "down", 3)
    assert result.success is True
    mock_fallback.scroll.assert_awaited_once()


@pytest.mark.asyncio
async def test_drag_falls_back_on_mcp_failure(backend: CuaDriverBackend, mock_fallback: MagicMock):
    backend._mcp._started = True
    backend._mcp.call_tool = AsyncMock(side_effect=RuntimeError("connection failed"))
    _stub_resolve(backend)

    result = await backend.drag(0, 0, 100, 100)
    assert result.success is True
    mock_fallback.drag.assert_awaited_once()


@pytest.mark.asyncio
async def test_mouse_move_falls_back_on_mcp_failure(backend: CuaDriverBackend, mock_fallback: MagicMock):
    backend._mcp._started = True
    backend._mcp.call_tool = AsyncMock(side_effect=RuntimeError("connection failed"))
    _stub_resolve(backend)

    result = await backend.mouse_move(50, 50)
    assert result.success is True
    mock_fallback.mouse_move.assert_awaited_once()


# ── Success path via cua-driver ───────────────────────────────────

@pytest.mark.asyncio
async def test_click_via_cua_driver_success(backend: CuaDriverBackend):
    backend._mcp._started = True
    backend._mcp.call_tool = AsyncMock(return_value=_make_mcp_result("ok"))
    _stub_resolve(backend)

    result = await backend.click(100, 200)
    assert result.success is True
    backend._mcp.call_tool.assert_awaited_once_with("click", {"pid": 12345, "x": 100, "y": 200})


@pytest.mark.asyncio
async def test_right_click_routes_correctly(backend: CuaDriverBackend):
    backend._mcp._started = True
    backend._mcp.call_tool = AsyncMock(return_value=_make_mcp_result("ok"))
    _stub_resolve(backend)

    result = await backend.click(100, 200, button="right")
    assert result.success is True
    backend._mcp.call_tool.assert_awaited_once_with("right_click", {"pid": 12345, "x": 100, "y": 200})


@pytest.mark.asyncio
async def test_double_click_routes_correctly(backend: CuaDriverBackend):
    backend._mcp._started = True
    backend._mcp.call_tool = AsyncMock(return_value=_make_mcp_result("ok"))
    _stub_resolve(backend)

    result = await backend.click(100, 200, clicks=2)
    assert result.success is True
    backend._mcp.call_tool.assert_awaited_once_with("double_click", {"pid": 12345, "x": 100, "y": 200})


@pytest.mark.asyncio
async def test_click_with_modifiers(backend: CuaDriverBackend):
    backend._mcp._started = True
    backend._mcp.call_tool = AsyncMock(return_value=_make_mcp_result("ok"))
    _stub_resolve(backend)

    result = await backend.click(100, 200, modifiers=["meta", "shift"])
    assert result.success is True
    call_args = backend._mcp.call_tool.call_args
    assert call_args[0][1]["modifier"] == ["cmd", "shift"]


@pytest.mark.asyncio
async def test_type_text_via_cua_driver(backend: CuaDriverBackend):
    backend._mcp._started = True
    backend._mcp.call_tool = AsyncMock(return_value=_make_mcp_result("ok"))
    _stub_resolve(backend)

    result = await backend.type_text("hello world")
    assert result.success is True
    backend._mcp.call_tool.assert_awaited_once_with("type_text", {"pid": 12345, "text": "hello world"})


@pytest.mark.asyncio
async def test_key_hotkey(backend: CuaDriverBackend):
    """cmd+s should route to hotkey tool."""
    backend._mcp._started = True
    backend._mcp.call_tool = AsyncMock(return_value=_make_mcp_result("ok"))
    _stub_resolve(backend)

    result = await backend.key("command+s")
    assert result.success is True
    backend._mcp.call_tool.assert_awaited_once_with("hotkey", {"pid": 12345, "keys": ["cmd", "s"]})


@pytest.mark.asyncio
async def test_key_single(backend: CuaDriverBackend):
    """Single key press should route to press_key tool."""
    backend._mcp._started = True
    backend._mcp.call_tool = AsyncMock(return_value=_make_mcp_result("ok"))
    _stub_resolve(backend)

    result = await backend.key("Return")
    assert result.success is True
    backend._mcp.call_tool.assert_awaited_once_with("press_key", {"pid": 12345, "key": "return"})


@pytest.mark.asyncio
async def test_scroll_via_cua_driver(backend: CuaDriverBackend):
    backend._mcp._started = True
    backend._mcp.call_tool = AsyncMock(return_value=_make_mcp_result("ok"))
    _stub_resolve(backend)

    result = await backend.scroll(100, 200, "down", 5)
    assert result.success is True
    call_args = backend._mcp.call_tool.call_args[0][1]
    assert call_args["direction"] == "down"
    assert call_args["amount"] == 5


@pytest.mark.asyncio
async def test_drag_via_cua_driver(backend: CuaDriverBackend):
    backend._mcp._started = True
    backend._mcp.call_tool = AsyncMock(return_value=_make_mcp_result("ok"))
    _stub_resolve(backend)

    result = await backend.drag(10, 20, 100, 200)
    assert result.success is True
    call_args = backend._mcp.call_tool.call_args[0][1]
    assert call_args == {"pid": 12345, "from_x": 10, "from_y": 20, "to_x": 100, "to_y": 200}


# ── resolve_target (PID resolution) ──────────────────────────────

@pytest.mark.asyncio
async def test_resolve_target_from_list_windows(backend: CuaDriverBackend):
    """_resolve_target should pick the frontmost on-screen window's PID."""
    structured = {
        "windows": [
            {"app_name": "Safari", "pid": 123, "window_id": 456, "z_index": 0, "is_on_screen": True}
        ]
    }
    backend._mcp._started = True
    backend._mcp.call_tool = AsyncMock(side_effect=[
        {"data": None, "images": [], "structuredContent": structured, "isError": False},
        _make_mcp_result("ok"),
    ])

    result = await backend.click(100, 200)
    assert result.success is True
    backend._mcp.call_tool.assert_any_await("list_windows", {"on_screen_only": True})


@pytest.mark.asyncio
async def test_resolve_target_no_caching(backend: CuaDriverBackend):
    """_resolve_target must re-query every call — no PID caching."""
    windows_safari = {
        "windows": [{"app_name": "Safari", "pid": 100, "window_id": 1, "z_index": 0, "is_on_screen": True}]
    }
    windows_notes = {
        "windows": [{"app_name": "Notes", "pid": 200, "window_id": 2, "z_index": 0, "is_on_screen": True}]
    }
    backend._mcp._started = True
    backend._mcp.call_tool = AsyncMock(side_effect=[
        {"data": None, "images": [], "structuredContent": windows_safari, "isError": False},
        _make_mcp_result("ok"),
        {"data": None, "images": [], "structuredContent": windows_notes, "isError": False},
        _make_mcp_result("ok"),
    ])

    await backend.click(10, 20)
    first_click_args = backend._mcp.call_tool.call_args_list[1]
    assert first_click_args[0][1]["pid"] == 100

    await backend.click(30, 40)
    second_click_args = backend._mcp.call_tool.call_args_list[3]
    assert second_click_args[0][1]["pid"] == 200


# ── _extract_result ───────────────────────────────────────────────

def test_extract_result_text():
    mock_result = MagicMock()
    mock_result.isError = False
    mock_result.structuredContent = None
    text_part = MagicMock()
    text_part.type = "text"
    text_part.text = "hello"
    mock_result.content = [text_part]

    out = _extract_result(mock_result)
    assert out["data"] == "hello"
    assert out["isError"] is False


def test_extract_result_image():
    mock_result = MagicMock()
    mock_result.isError = False
    mock_result.structuredContent = None
    img_part = MagicMock()
    img_part.type = "image"
    img_part.data = "base64data"
    mock_result.content = [img_part]

    out = _extract_result(mock_result)
    assert out["images"] == ["base64data"]


# ── is_cua_driver_available ───────────────────────────────────────

def test_is_cua_driver_available_false():
    with patch("shutil.which", return_value=None):
        assert is_cua_driver_available() is False


def test_is_cua_driver_available_true():
    with patch("shutil.which", return_value="/usr/local/bin/cua-driver"):
        assert is_cua_driver_available() is True


# ── Session factory fallback ──────────────────────────────────────

def test_session_factory_no_cua_driver():
    """When cua-driver is absent, factory should return native backend unchanged."""
    from myrm_agent_harness.toolkits.computer_use.session import _try_wrap_with_cua_driver

    native = MagicMock()
    with patch(
        "myrm_agent_harness.toolkits.computer_use.backends.cua_driver.is_cua_driver_available",
        return_value=False,
    ):
        result = _try_wrap_with_cua_driver(native)
    assert result is native


def test_session_factory_with_cua_driver():
    """When cua-driver is present, factory should wrap with CuaDriverBackend."""
    from myrm_agent_harness.toolkits.computer_use.session import _try_wrap_with_cua_driver

    native = MagicMock()
    with patch(
        "myrm_agent_harness.toolkits.computer_use.backends.cua_driver.is_cua_driver_available",
        return_value=True,
    ):
        result = _try_wrap_with_cua_driver(native)
    assert isinstance(result, CuaDriverBackend)


# ── Error result from cua-driver triggers fallback ────────────────

@pytest.mark.asyncio
async def test_click_falls_back_on_cua_error_result(backend: CuaDriverBackend, mock_fallback: MagicMock):
    """When cua-driver returns isError=True, click should fall back."""
    backend._mcp._started = True
    backend._mcp.call_tool = AsyncMock(return_value=_make_mcp_result("error detail", is_error=True))
    _stub_resolve(backend)

    result = await backend.click(100, 200)
    assert result.success is True
    mock_fallback.click.assert_awaited_once()


# ── ComputerSession.close() lifecycle ─────────────────────────────

@pytest.mark.asyncio
async def test_computer_session_close_calls_backend_close():
    """ComputerSession.close() should call backend.close() when available."""
    from myrm_agent_harness.toolkits.computer_use.session import ComputerSession

    fb = MagicMock()
    fb.screen_info = MagicMock(return_value=ScreenInfo(width=1920, height=1080, dpi_scale=1.0))
    backend = CuaDriverBackend(fallback=fb)
    backend.close = AsyncMock()  # type: ignore[method-assign]

    session = ComputerSession(backend=backend)
    await session.close()
    backend.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_computer_session_close_noop_for_native_backend():
    """ComputerSession.close() should be a no-op for backends without close()."""
    from myrm_agent_harness.toolkits.computer_use.backends.protocols import ComputerBackend
    from myrm_agent_harness.toolkits.computer_use.session import ComputerSession

    native = MagicMock(spec=ComputerBackend)
    native.screen_info = MagicMock(return_value=ScreenInfo(width=1920, height=1080, dpi_scale=1.0))

    session = ComputerSession(backend=native)
    await session.close()  # should not raise, no close() on spec'd mock
