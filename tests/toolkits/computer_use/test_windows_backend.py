"""Tests for WindowsBackend — mss + pyautogui + ctypes.

Covers:
- WindowsBackend instantiation and protocol compliance
- click/scroll/drag with modifier key handling (keyDown/keyUp guarantee)
- type_text() ASCII and non-ASCII (clipboard paste)
- key() single and combo keys
- mouse_move(), wait(), screen_info(), screen_context(), window_text()
- Clipboard Win32 API functions
- Factory function: create_computer_session routes to WindowsBackend
"""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.computer_use.types import (
    ScreenContext,
    ScreenInfo,
    WindowTextResult,
)


def _mock_pyautogui() -> MagicMock:
    """Create a fully mocked pyautogui."""
    m = MagicMock()
    m.size.return_value = MagicMock(width=1920, height=1080)
    m.position.return_value = MagicMock(x=100, y=200)
    for name in ("keyDown", "keyUp", "click", "scroll", "hscroll", "moveTo",
                 "drag", "write", "press", "hotkey"):
        fn = MagicMock()
        fn.__name__ = name
        setattr(m, name, fn)
    return m


_MOCK_MODULES_BASE = {
    "mss": MagicMock(),
    "mss.tools": MagicMock(),
    "mouseinfo": MagicMock(),
    "uiautomation": MagicMock(),
    "rubicon": MagicMock(),
    "rubicon.objc": MagicMock(),
    "rubicon.objc.api": MagicMock(),
    "rubicon.objc.runtime": MagicMock(),
    "rubicon.objc.collections": MagicMock(),
    "rubicon.objc.types": MagicMock(),
    "AppKit": MagicMock(),
}


@pytest.fixture
def _mock_windows_env():
    """Fixture that mocks all Windows-specific dependencies for testing on any platform."""
    mock_pyautogui = _mock_pyautogui()

    mock_windll = MagicMock()
    mock_windll.user32.GetSystemMetrics.side_effect = lambda x: 1920 if x == 0 else 1080
    mock_windll.user32.GetDpiForSystem.return_value = 144
    mock_windll.user32.GetForegroundWindow.return_value = 12345
    mock_windll.user32.GetWindowTextLengthW.return_value = 7
    mock_windll.user32.GetWindowTextW.return_value = None
    mock_windll.user32.OpenClipboard.return_value = True
    mock_windll.user32.CloseClipboard.return_value = True
    mock_windll.user32.EmptyClipboard.return_value = True
    mock_windll.user32.SetClipboardData.return_value = True
    mock_windll.user32.GetClipboardData.return_value = 1
    mock_windll.user32.SetProcessDPIAware.return_value = None
    mock_windll.kernel32.GlobalAlloc.return_value = 1
    mock_windll.kernel32.GlobalLock.return_value = 1
    mock_windll.kernel32.GlobalUnlock.return_value = True
    mock_windll.kernel32.GlobalFree.return_value = None
    mock_windll.shcore.SetProcessDpiAwareness.return_value = None

    modules = {**_MOCK_MODULES_BASE, "pyautogui": mock_pyautogui}
    with patch.dict("sys.modules", modules):
        import ctypes as real_ctypes
        with patch.object(real_ctypes, "windll", mock_windll, create=True):
            with patch.object(real_ctypes, "wstring_at", return_value="clipboard text", create=True):
                with patch.object(real_ctypes, "create_unicode_buffer", return_value=MagicMock(value="Notepad")):
                    # Reload windows module with mocked ctypes
                    import myrm_agent_harness.toolkits.computer_use.backends.windows as win_mod
                    importlib.reload(win_mod)
                    yield win_mod, mock_pyautogui, mock_windll


@pytest.mark.usefixtures("_mock_windows_env")
class TestWindowsBackendModifiers:
    """WindowsBackend modifier key handling."""

    @pytest.fixture
    def backend(self, _mock_windows_env):
        win_mod, _, _ = _mock_windows_env
        return win_mod.WindowsBackend()

    @pytest.mark.asyncio
    async def test_click_with_modifiers(self, backend) -> None:
        call_log: list[tuple[str, tuple]] = []

        async def mock_to_thread(fn, *args, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            call_log.append((name, args))
            return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            result = await backend.click(100, 200, modifiers=["ctrl", "shift"])

        assert result.success is True
        names = [c[0] for c in call_log]
        assert names == ["keyDown", "keyDown", "click", "keyUp", "keyUp"]
        assert call_log[0][1] == ("ctrl",)
        assert call_log[1][1] == ("shift",)
        assert call_log[3][1] == ("shift",)
        assert call_log[4][1] == ("ctrl",)

    @pytest.mark.asyncio
    async def test_click_without_modifiers(self, backend) -> None:
        call_log: list[tuple[str, tuple]] = []

        async def mock_to_thread(fn, *args, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            call_log.append((name, args))
            return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            result = await backend.click(100, 200)

        assert result.success is True
        names = [c[0] for c in call_log]
        assert "keyDown" not in names
        assert "keyUp" not in names

    @pytest.mark.asyncio
    async def test_click_exception_releases_modifiers(self, backend) -> None:
        call_log: list[tuple[str, tuple]] = []

        async def mock_to_thread(fn, *args, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            call_log.append((name, args))
            if name == "click":
                raise RuntimeError("simulated failure")
            return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            result = await backend.click(100, 200, modifiers=["ctrl"])

        assert result.success is False
        assert "simulated failure" in (result.error or "")
        names = [c[0] for c in call_log]
        assert "keyDown" in names
        assert "keyUp" in names

    @pytest.mark.asyncio
    async def test_meta_maps_to_win(self, backend) -> None:
        call_log: list[tuple[str, tuple]] = []

        async def mock_to_thread(fn, *args, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            call_log.append((name, args))
            return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            await backend.click(100, 200, modifiers=["meta"])

        keydown_args = [c[1] for c in call_log if c[0] == "keyDown"]
        assert keydown_args[0] == ("win",)

    @pytest.mark.asyncio
    async def test_scroll_with_modifiers(self, backend) -> None:
        call_log: list[tuple[str, tuple]] = []

        async def mock_to_thread(fn, *args, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            call_log.append((name, args))
            return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            result = await backend.scroll(100, 200, "down", 3, modifiers=["ctrl"])

        assert result.success is True
        names = [c[0] for c in call_log]
        assert names.count("keyDown") == 1
        assert names.count("keyUp") == 1

    @pytest.mark.asyncio
    async def test_drag_with_modifiers(self, backend) -> None:
        call_log: list[tuple[str, tuple]] = []

        async def mock_to_thread(fn, *args, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            call_log.append((name, args))
            return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            result = await backend.drag(10, 20, 100, 200, modifiers=["alt"])

        assert result.success is True
        names = [c[0] for c in call_log]
        assert names.count("keyDown") == 1
        assert names.count("keyUp") == 1


class TestWindowsBackendTypeText:
    """type_text ASCII and non-ASCII paths."""

    @pytest.fixture
    def backend(self, _mock_windows_env):
        win_mod, _, _ = _mock_windows_env
        return win_mod.WindowsBackend()

    @pytest.mark.asyncio
    async def test_ascii_text_uses_write(self, backend) -> None:
        call_log: list[tuple[str, tuple]] = []

        async def mock_to_thread(fn, *args, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            call_log.append((name, args + tuple(kwargs.values())))
            return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            result = await backend.type_text("hello")

        assert result.success is True
        names = [c[0] for c in call_log]
        assert "write" in names

    @pytest.mark.asyncio
    async def test_non_ascii_uses_clipboard_paste(self, backend) -> None:
        call_log: list[tuple[str, tuple]] = []

        async def mock_to_thread(fn, *args, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            call_log.append((name, args))
            return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            result = await backend.type_text("你好世界")

        assert result.success is True
        names = [c[0] for c in call_log]
        assert "hotkey" in names


class TestWindowsBackendKey:
    """key() single and combo."""

    @pytest.fixture
    def backend(self, _mock_windows_env):
        win_mod, _, _ = _mock_windows_env
        return win_mod.WindowsBackend()

    @pytest.mark.asyncio
    async def test_single_key(self, backend) -> None:
        call_log: list[tuple[str, tuple]] = []

        async def mock_to_thread(fn, *args, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            call_log.append((name, args))
            return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            result = await backend.key("Return")

        assert result.success is True
        names = [c[0] for c in call_log]
        assert "press" in names

    @pytest.mark.asyncio
    async def test_combo_key(self, backend) -> None:
        call_log: list[tuple[str, tuple]] = []

        async def mock_to_thread(fn, *args, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            call_log.append((name, args))
            return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            result = await backend.key("ctrl+c")

        assert result.success is True
        names = [c[0] for c in call_log]
        assert "hotkey" in names


class TestWindowsBackendWait:
    """wait() tests."""

    @pytest.fixture
    def backend(self, _mock_windows_env):
        win_mod, _, _ = _mock_windows_env
        return win_mod.WindowsBackend()

    @pytest.mark.asyncio
    async def test_wait(self, backend) -> None:
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await backend.wait(1.5)

        assert result.success is True
        mock_sleep.assert_called_once_with(1.5)


class TestWindowsBackendScreenInfo:
    """screen_info() and DPI detection."""

    @pytest.fixture
    def backend(self, _mock_windows_env):
        win_mod, _, _ = _mock_windows_env
        return win_mod.WindowsBackend()

    def test_screen_info_returns_correct_type(self, backend, _mock_windows_env) -> None:
        win_mod, _, _ = _mock_windows_env
        with patch.object(
            win_mod, "_detect_screen_info", return_value=(1920, 1080, 1.5),
        ):
            info = backend.screen_info()

        assert isinstance(info, ScreenInfo)
        assert info.width == 1920
        assert info.height == 1080
        assert info.dpi_scale == 1.5

    def test_screen_info_cached(self, backend, _mock_windows_env) -> None:
        win_mod, _, _ = _mock_windows_env
        with patch.object(
            win_mod, "_detect_screen_info", return_value=(1920, 1080, 2.0),
        ) as mock_detect:
            backend.screen_info()
            backend.screen_info()

        mock_detect.assert_called_once()


class TestWindowsBackendScreenContext:
    """screen_context() tests."""

    @pytest.fixture
    def backend(self, _mock_windows_env):
        win_mod, _, _ = _mock_windows_env
        return win_mod.WindowsBackend()

    def test_screen_context(self, backend, _mock_windows_env) -> None:
        win_mod, mock_pyautogui, _ = _mock_windows_env
        mock_pyautogui.position.return_value = MagicMock(x=300, y=400)
        with patch.object(win_mod, "_get_active_window_title", return_value="VS Code"):
            ctx = backend.screen_context()

        assert isinstance(ctx, ScreenContext)
        assert ctx.active_window == "VS Code"
        assert ctx.mouse_x == 300
        assert ctx.mouse_y == 400


class TestWindowsBackendWindowText:
    """window_text() via uiautomation."""

    @pytest.fixture
    def backend(self, _mock_windows_env):
        win_mod, _, _ = _mock_windows_env
        return win_mod.WindowsBackend()

    @pytest.mark.asyncio
    async def test_window_text_success(self, backend) -> None:
        with patch("asyncio.to_thread", return_value=WindowTextResult(
            app_name="Notepad", window_title="Notepad", text="Hello", success=True,
        )):
            result = await backend.window_text()

        assert result.success is True
        assert result.app_name == "Notepad"

    @pytest.mark.asyncio
    async def test_window_text_failure(self, backend) -> None:
        with patch("asyncio.to_thread", return_value=WindowTextResult(success=False)):
            result = await backend.window_text()

        assert result.success is False

    @pytest.mark.asyncio
    async def test_has_blocking_dialog_true(self, backend, _mock_windows_env) -> None:
        win_mod, _, mock_windll = _mock_windows_env
        mock_windll.user32.GetForegroundWindow.return_value = 12345
        
        def mock_get_class_name(hwnd, buf, size):
            buf.value = "#32770"
            return len("#32770")
        mock_windll.user32.GetClassNameW.side_effect = mock_get_class_name
        
        def mock_get_window_text_length(hwnd):
            return len("Google Chrome")
        mock_windll.user32.GetWindowTextLengthW.side_effect = mock_get_window_text_length
        
        def mock_get_window_text(hwnd, buf, size):
            buf.value = "Google Chrome"
            return len("Google Chrome")
        mock_windll.user32.GetWindowTextW.side_effect = mock_get_window_text
        
        with patch("asyncio.to_thread", side_effect=lambda fn, *args: fn(*args)):
            result = await backend.has_blocking_dialog(["Google Chrome"])
        assert result is True

    @pytest.mark.asyncio
    async def test_has_blocking_dialog_false(self, backend, _mock_windows_env) -> None:
        win_mod, _, mock_windll = _mock_windows_env
        mock_windll.user32.GetForegroundWindow.return_value = 12345
        
        def mock_get_class_name(hwnd, buf, size):
            buf.value = "Chrome_WidgetWin_1"
            return len("Chrome_WidgetWin_1")
        mock_windll.user32.GetClassNameW.side_effect = mock_get_class_name
        
        with patch("asyncio.to_thread", side_effect=lambda fn, *args: fn(*args)):
            result = await backend.has_blocking_dialog(["Google Chrome"])
        assert result is False

    @pytest.mark.asyncio
    async def test_has_blocking_dialog_exception(self, backend, _mock_windows_env) -> None:
        win_mod, _, mock_windll = _mock_windows_env
        mock_windll.user32.GetForegroundWindow.side_effect = Exception("error")
        
        with patch("asyncio.to_thread", side_effect=lambda fn, *args: fn(*args)):
            result = await backend.has_blocking_dialog(["Google Chrome"])
        assert result is False

    @pytest.mark.asyncio
    async def test_is_browser_active_true(self, backend, _mock_windows_env) -> None:
        win_mod, _, mock_windll = _mock_windows_env
        mock_windll.user32.GetForegroundWindow.return_value = 12345
        
        def mock_get_window_text_length(hwnd):
            return len("Google Chrome")
        mock_windll.user32.GetWindowTextLengthW.side_effect = mock_get_window_text_length
        
        def mock_get_window_text(hwnd, buf, size):
            buf.value = "Google Chrome"
            return len("Google Chrome")
        mock_windll.user32.GetWindowTextW.side_effect = mock_get_window_text
        
        with patch("asyncio.to_thread", side_effect=lambda fn, *args: fn(*args)):
            result = await backend.is_browser_active()
        assert result is True

    @pytest.mark.asyncio
    async def test_is_browser_active_false(self, backend, _mock_windows_env) -> None:
        win_mod, _, mock_windll = _mock_windows_env
        mock_windll.user32.GetForegroundWindow.return_value = 12345
        
        def mock_get_window_text_length(hwnd):
            return len("Notepad")
        mock_windll.user32.GetWindowTextLengthW.side_effect = mock_get_window_text_length
        
        def mock_get_window_text(hwnd, buf, size):
            buf.value = "Notepad"
            return len("Notepad")
        mock_windll.user32.GetWindowTextW.side_effect = mock_get_window_text
        
        with patch("asyncio.to_thread", side_effect=lambda fn, *args: fn(*args)):
            result = await backend.is_browser_active()
        assert result is False


class TestCreateComputerSessionWindows:
    """Factory function routes to WindowsBackend on Windows."""

    def test_windows_platform_creates_windows_backend(self, _mock_windows_env) -> None:
        win_mod, _, _ = _mock_windows_env
        mock_platform_info = MagicMock()
        mock_platform_info.os_type = "windows"

        with patch(
            "myrm_agent_harness.toolkits.code_execution.platform.detect_platform",
            return_value=mock_platform_info,
        ):
            from myrm_agent_harness.toolkits.computer_use.session import create_computer_session
            session = create_computer_session()

        assert isinstance(session._backend, win_mod.WindowsBackend)


class TestWindowsBackendScreenshot:
    """screenshot() via mss."""

    @pytest.fixture
    def backend(self, _mock_windows_env):
        win_mod, _, _ = _mock_windows_env
        return win_mod.WindowsBackend()

    @pytest.mark.asyncio
    async def test_screenshot_returns_png_bytes(self, backend) -> None:
        fake_png = b"\x89PNG\r\n\x1a\n"

        async def mock_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs) if not args else fn()

        with patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: asyncio.coroutine(lambda: fake_png)()):
            with patch("asyncio.to_thread", return_value=fake_png):
                result = await backend.screenshot()

        assert isinstance(result, bytes)


class TestWindowsBackendMouseMove:
    """mouse_move() tests."""

    @pytest.fixture
    def backend(self, _mock_windows_env):
        win_mod, _, _ = _mock_windows_env
        return win_mod.WindowsBackend()

    @pytest.mark.asyncio
    async def test_mouse_move_success(self, backend) -> None:
        call_log: list[tuple[str, tuple]] = []

        async def mock_to_thread(fn, *args, **kwargs):
            call_log.append((getattr(fn, "__name__", str(fn)), args))
            return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            result = await backend.mouse_move(500, 600)

        assert result.success is True
        assert call_log[0] == ("moveTo", (500, 600))

    @pytest.mark.asyncio
    async def test_mouse_move_failure(self, backend) -> None:
        async def mock_to_thread(fn, *args, **kwargs):
            raise OSError("display not available")

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            result = await backend.mouse_move(0, 0)

        assert result.success is False
        assert "display not available" in (result.error or "")


class TestWindowsBackendScrollDirections:
    """scroll() direction and amount logic."""

    @pytest.fixture
    def backend(self, _mock_windows_env):
        win_mod, _, _ = _mock_windows_env
        return win_mod.WindowsBackend()

    @pytest.mark.asyncio
    async def test_scroll_up_positive_amount(self, backend) -> None:
        call_log: list[tuple[str, tuple]] = []

        async def mock_to_thread(fn, *args, **kwargs):
            call_log.append((getattr(fn, "__name__", str(fn)), args))
            return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            await backend.scroll(50, 50, "up", 5)

        scroll_calls = [(n, a) for n, a in call_log if n == "scroll"]
        assert scroll_calls[0][1] == (5,)

    @pytest.mark.asyncio
    async def test_scroll_down_negative_amount(self, backend) -> None:
        call_log: list[tuple[str, tuple]] = []

        async def mock_to_thread(fn, *args, **kwargs):
            call_log.append((getattr(fn, "__name__", str(fn)), args))
            return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            await backend.scroll(50, 50, "down", 3)

        scroll_calls = [(n, a) for n, a in call_log if n == "scroll"]
        assert scroll_calls[0][1] == (-3,)

    @pytest.mark.asyncio
    async def test_scroll_left_uses_hscroll(self, backend) -> None:
        call_log: list[tuple[str, tuple]] = []

        async def mock_to_thread(fn, *args, **kwargs):
            call_log.append((getattr(fn, "__name__", str(fn)), args))
            return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            await backend.scroll(50, 50, "left", 2)

        hscroll_calls = [(n, a) for n, a in call_log if n == "hscroll"]
        assert hscroll_calls[0][1] == (2,)

    @pytest.mark.asyncio
    async def test_scroll_right_uses_hscroll_negative(self, backend) -> None:
        call_log: list[tuple[str, tuple]] = []

        async def mock_to_thread(fn, *args, **kwargs):
            call_log.append((getattr(fn, "__name__", str(fn)), args))
            return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            await backend.scroll(50, 50, "right", 4)

        hscroll_calls = [(n, a) for n, a in call_log if n == "hscroll"]
        assert hscroll_calls[0][1] == (-4,)

    @pytest.mark.asyncio
    async def test_scroll_exception_releases_modifiers(self, backend) -> None:
        call_log: list[tuple[str, tuple]] = []

        async def mock_to_thread(fn, *args, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            call_log.append((name, args))
            if name == "scroll":
                raise RuntimeError("scroll failed")
            return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            result = await backend.scroll(50, 50, "up", 3, modifiers=["shift"])

        assert result.success is False
        names = [c[0] for c in call_log]
        assert "keyUp" in names


class TestWindowsBackendTypeTextEdgeCases:
    """type_text edge cases: chunking, empty, failure."""

    @pytest.fixture
    def backend(self, _mock_windows_env):
        win_mod, _, _ = _mock_windows_env
        return win_mod.WindowsBackend()

    @pytest.mark.asyncio
    async def test_large_text_chunked(self, backend) -> None:
        """Text longer than chunk_size triggers multiple write calls."""
        call_log: list[tuple[str, tuple]] = []

        async def mock_to_thread(fn, *args, **kwargs):
            call_log.append((getattr(fn, "__name__", str(fn)), args))
            return None

        long_text = "a" * 120
        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            result = await backend.type_text(long_text, chunk_size=50)

        assert result.success is True
        write_calls = [c for c in call_log if c[0] == "write"]
        assert len(write_calls) == 3  # 50+50+20

    @pytest.mark.asyncio
    async def test_empty_text(self, backend) -> None:
        call_log: list[tuple[str, tuple]] = []

        async def mock_to_thread(fn, *args, **kwargs):
            call_log.append((getattr(fn, "__name__", str(fn)), args))
            return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            result = await backend.type_text("")

        assert result.success is True

    @pytest.mark.asyncio
    async def test_type_text_exception(self, backend) -> None:
        async def mock_to_thread(fn, *args, **kwargs):
            raise RuntimeError("keyboard unavailable")

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            result = await backend.type_text("hello")

        assert result.success is False
        assert "keyboard unavailable" in (result.error or "")


class TestWindowsBackendDragEdgeCases:
    """drag() edge cases."""

    @pytest.fixture
    def backend(self, _mock_windows_env):
        win_mod, _, _ = _mock_windows_env
        return win_mod.WindowsBackend()

    @pytest.mark.asyncio
    async def test_drag_exception_releases_modifiers(self, backend) -> None:
        call_log: list[tuple[str, tuple]] = []

        async def mock_to_thread(fn, *args, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            call_log.append((name, args))
            if name == "drag":
                raise RuntimeError("drag failed")
            return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            result = await backend.drag(0, 0, 100, 100, modifiers=["ctrl", "alt"])

        assert result.success is False
        names = [c[0] for c in call_log]
        assert names.count("keyUp") == 2

    @pytest.mark.asyncio
    async def test_drag_without_modifiers(self, backend) -> None:
        call_log: list[tuple[str, tuple]] = []

        async def mock_to_thread(fn, *args, **kwargs):
            call_log.append((getattr(fn, "__name__", str(fn)), args))
            return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            result = await backend.drag(10, 20, 100, 200)

        assert result.success is True
        names = [c[0] for c in call_log]
        assert "keyDown" not in names
        assert "keyUp" not in names
        assert "moveTo" in names
        assert "drag" in names


class TestWindowsBackendClipboard:
    """Direct tests for _get_clipboard and _set_clipboard."""

    def test_get_clipboard_success(self, _mock_windows_env) -> None:
        win_mod, _, _mock_windll = _mock_windows_env
        result = win_mod._get_clipboard()
        assert result == "clipboard text"

    def test_get_clipboard_open_fails(self, _mock_windows_env) -> None:
        win_mod, _, mock_windll = _mock_windows_env
        mock_windll.user32.OpenClipboard.return_value = False
        result = win_mod._get_clipboard()
        assert result is None

    def test_get_clipboard_no_data(self, _mock_windows_env) -> None:
        win_mod, _, mock_windll = _mock_windows_env
        mock_windll.user32.GetClipboardData.return_value = 0
        result = win_mod._get_clipboard()
        assert result is None

    def test_set_clipboard_success(self, _mock_windows_env) -> None:
        win_mod, _, mock_windll = _mock_windows_env
        with patch("ctypes.memmove"):
            win_mod._set_clipboard("test data")
        mock_windll.user32.EmptyClipboard.assert_called_once()
        mock_windll.user32.SetClipboardData.assert_called_once()

    def test_set_clipboard_alloc_fails(self, _mock_windows_env) -> None:
        win_mod, _, mock_windll = _mock_windows_env
        mock_windll.kernel32.GlobalAlloc.return_value = 0
        with patch("ctypes.memmove"):
            win_mod._set_clipboard("test")  # Should not raise


class TestWindowsBackendDetectScreenInfo:
    """_detect_screen_info DPI fallback paths."""

    def test_dpi_from_get_dpi_for_system(self, _mock_windows_env) -> None:
        win_mod, _, mock_windll = _mock_windows_env
        mock_windll.user32.GetDpiForSystem.return_value = 192
        w, h, scale = win_mod._detect_screen_info()
        assert w == 1920
        assert h == 1080
        assert scale == 2.0

    def test_dpi_fallback_to_pyautogui(self, _mock_windows_env) -> None:
        """When ctypes.windll fails entirely, falls back to pyautogui.size()."""
        win_mod, mock_pyautogui, mock_windll = _mock_windows_env
        mock_windll.user32.GetSystemMetrics.side_effect = Exception("no display")
        mock_pyautogui.size.return_value = MagicMock(width=2560, height=1440)
        w, h, scale = win_mod._detect_screen_info()
        assert w == 2560
        assert h == 1440
        assert scale == 1.0


class TestWindowsBackendWindowTextExtraction:
    """_extract_window_text_uia with recursive text collection."""

    def test_import_error_returns_failure(self, _mock_windows_env) -> None:
        win_mod, _, _ = _mock_windows_env
        with patch.dict("sys.modules", {"uiautomation": None}):
            with patch("builtins.__import__", side_effect=ImportError("no module")):
                result = win_mod._extract_window_text_uia()
        assert result.success is False

    def test_no_foreground_control(self, _mock_windows_env) -> None:
        win_mod, _, _ = _mock_windows_env
        mock_auto = MagicMock()
        mock_auto.GetForegroundControl.return_value = None
        with patch.dict("sys.modules", {"uiautomation": mock_auto}):
            result = win_mod._extract_window_text_uia()
        assert result.success is False

    def test_collect_text_recursive_depth_limit(self, _mock_windows_env) -> None:
        win_mod, _, _ = _mock_windows_env
        text_parts: list[str] = []
        mock_control = MagicMock()
        mock_control.GetChildren.return_value = []
        win_mod._collect_text_recursive(mock_control, text_parts, max_depth=0, max_elements=100)
        assert text_parts == []

    def test_collect_text_recursive_max_elements(self, _mock_windows_env) -> None:
        win_mod, _, _ = _mock_windows_env
        text_parts = ["x"] * 500
        mock_control = MagicMock()
        win_mod._collect_text_recursive(mock_control, text_parts, max_depth=5, max_elements=500)
        assert len(text_parts) == 500


class TestModifierMapping:
    """_MODIFIER_TO_PYAUTOGUI mapping correctness."""

    def test_all_modifiers_mapped(self, _mock_windows_env) -> None:
        win_mod, _, _ = _mock_windows_env
        assert win_mod._MODIFIER_TO_PYAUTOGUI["ctrl"] == "ctrl"
        assert win_mod._MODIFIER_TO_PYAUTOGUI["shift"] == "shift"
        assert win_mod._MODIFIER_TO_PYAUTOGUI["alt"] == "alt"
        assert win_mod._MODIFIER_TO_PYAUTOGUI["meta"] == "win"
