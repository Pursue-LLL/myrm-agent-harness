import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock pyautogui before importing MacOSBackend
sys.modules['pyautogui'] = MagicMock()

from myrm_agent_harness.toolkits.computer_use.backends.macos import (
    MacOSBackend,
    _detect_dpi_scale_quartz,
    _has_blocking_dialog,
    _is_browser_active,
)


@pytest.fixture
def backend():
    return MacOSBackend()

@pytest.mark.asyncio
async def test_screenshot(backend):
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc
        with patch("pathlib.Path.read_bytes", return_value=b"png"):
            res = await backend.screenshot()
            assert res == b"png"

@pytest.mark.asyncio
async def test_click(backend):
    with patch("asyncio.to_thread"):
        res = await backend.click(10, 20, modifiers=["ctrl"])
        assert res.success is True

@pytest.mark.asyncio
async def test_type_text_ascii(backend):
    with patch("asyncio.to_thread"):
        res = await backend.type_text("hello")
        assert res.success is True

@pytest.mark.asyncio
async def test_type_text_non_ascii(backend):
    with patch("asyncio.to_thread"):
        res = await backend.type_text("你好")
        assert res.success is True

@pytest.mark.asyncio
async def test_key(backend):
    with patch("asyncio.to_thread"):
        res = await backend.key("ctrl+c")
        assert res.success is True

@pytest.mark.asyncio
async def test_mouse_move(backend):
    with patch("asyncio.to_thread"):
        res = await backend.mouse_move(10, 20)
        assert res.success is True

@pytest.mark.asyncio
async def test_scroll(backend):
    with patch("asyncio.to_thread"):
        res = await backend.scroll(10, 20, "down", modifiers=["ctrl"])
        assert res.success is True

@pytest.mark.asyncio
async def test_drag(backend):
    with patch("asyncio.to_thread"):
        res = await backend.drag(10, 20, 30, 40, modifiers=["ctrl"])
        assert res.success is True

@pytest.mark.asyncio
async def test_wait(backend):
    with patch("asyncio.sleep"):
        res = await backend.wait(1.0)
        assert res.success is True

def test_screen_info(backend):
    with patch("pyautogui.size", return_value=MagicMock(width=1920, height=1080)):
        with patch("myrm_agent_harness.toolkits.computer_use.backends.macos._detect_dpi_scale_quartz", return_value=2.0):
            info = backend.screen_info()
            assert info.width == 1920
            assert info.height == 1080
            assert info.dpi_scale == 2.0

def test_screen_context(backend):
    with patch("pyautogui.position", return_value=MagicMock(x=10, y=20)):
        with patch("myrm_agent_harness.toolkits.computer_use.backends.macos._get_active_window_title", return_value="Title"):
            ctx = backend.screen_context()
            assert ctx.active_window == "Title"
            assert ctx.mouse_x == 10
            assert ctx.mouse_y == 20

@pytest.mark.asyncio
async def test_window_text(backend):
    with patch("asyncio.to_thread", return_value=MagicMock(success=True, window_title="Title")):
        res = await backend.window_text()
        assert res.success is True
        assert res.window_title == "Title"

def test_has_blocking_dialog_true():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="Google Chrome|||true")
        result = _has_blocking_dialog(["Google Chrome"])
        assert result is True

def test_has_blocking_dialog_false_no_dialog():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="Google Chrome|||false")
        result = _has_blocking_dialog(["Google Chrome"])
        assert result is False

def test_has_blocking_dialog_false_wrong_app():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="Firefox|||true")
        result = _has_blocking_dialog(["Google Chrome"])
        assert result is False

def test_has_blocking_dialog_exception():
    with patch("subprocess.run", side_effect=Exception("error")):
        result = _has_blocking_dialog(["Google Chrome"])
        assert result is False

def test_is_browser_active_true():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="Google Chrome")
        result = _is_browser_active()
        assert result is True

def test_is_browser_active_false():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="Finder")
        result = _is_browser_active()
        assert result is False

def test_is_browser_active_exception():
    with patch("subprocess.run", side_effect=Exception("error")):
        result = _is_browser_active()
        assert result is False

    def test_detect_dpi_scale_quartz():
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=b"Retina")
            assert _detect_dpi_scale_quartz(1920) == 2.0
