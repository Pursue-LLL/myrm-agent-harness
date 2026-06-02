import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from myrm_agent_harness.toolkits.computer_use.backends.linux import LinuxBackend, _parse_display_num, _detect_linux_resolution

@pytest.fixture
def backend():
    return LinuxBackend(display_num=1)

def test_parse_display_num():
    with patch("os.getenv", return_value=":99.0"):
        assert _parse_display_num() == 99
    with patch("os.getenv", return_value=""):
        assert _parse_display_num() is None

@pytest.mark.asyncio
async def test_run_cmd(backend):
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"out", b"err")
    mock_proc.returncode = 0
    with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
        out, err, code = await backend._run_cmd("test")
        assert out == "out"
        assert err == "err"
        assert code == 0

@pytest.mark.asyncio
async def test_screenshot(backend):
    with patch("shutil.which", return_value=True):
        with patch.object(backend, "_run_cmd", return_value=("", "", 0)):
            with patch("pathlib.Path.read_bytes", return_value=b"png"):
                res = await backend.screenshot()
                assert res == b"png"

@pytest.mark.asyncio
async def test_click(backend):
    with patch.object(backend, "_run_cmd", return_value=("", "", 0)):
        res = await backend.click(10, 20, modifiers=["ctrl"])
        assert res.success is True

@pytest.mark.asyncio
async def test_type_text_ascii(backend):
    with patch.object(backend, "_run_cmd", return_value=("", "", 0)):
        res = await backend.type_text("hello")
        assert res.success is True

@pytest.mark.asyncio
async def test_type_text_non_ascii(backend):
    with patch.object(backend, "_run_cmd", return_value=("", "", 0)):
        with patch("asyncio.create_subprocess_shell") as mock_shell:
            mock_proc = AsyncMock()
            mock_proc.communicate.return_value = (b"", b"")
            mock_shell.return_value = mock_proc
            res = await backend.type_text("你好")
            assert res.success is True

@pytest.mark.asyncio
async def test_key(backend):
    with patch.object(backend, "_run_cmd", return_value=("", "", 0)):
        res = await backend.key("ctrl+c")
        assert res.success is True

@pytest.mark.asyncio
async def test_mouse_move(backend):
    with patch.object(backend, "_run_cmd", return_value=("", "", 0)):
        res = await backend.mouse_move(10, 20)
        assert res.success is True

@pytest.mark.asyncio
async def test_scroll(backend):
    with patch.object(backend, "_run_cmd", return_value=("", "", 0)):
        res = await backend.scroll(10, 20, "down", modifiers=["ctrl"])
        assert res.success is True

@pytest.mark.asyncio
async def test_drag(backend):
    with patch.object(backend, "_run_cmd", return_value=("", "", 0)):
        res = await backend.drag(10, 20, 30, 40, modifiers=["ctrl"])
        assert res.success is True

@pytest.mark.asyncio
async def test_wait(backend):
    with patch("asyncio.sleep"):
        res = await backend.wait(1.0)
        assert res.success is True

def test_screen_info(backend):
    with patch("os.getenv", side_effect=["1920", "1080"]):
        info = backend.screen_info()
        assert info.width == 1920
        assert info.height == 1080

def test_screen_context(backend):
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="Title"),
            MagicMock(returncode=0, stdout="x:10 y:20")
        ]
        ctx = backend.screen_context()
        assert ctx.active_window == "Title"
        assert ctx.mouse_x == 10
        assert ctx.mouse_y == 20

@pytest.mark.asyncio
async def test_window_text(backend):
    with patch.object(backend, "_run_cmd", side_effect=[
        ("Title", "", 0),
        ("123", "", 0),
        ("Class", "", 0)
    ]):
        res = await backend.window_text()
        assert res.success is True
        assert res.window_title == "Title"

@pytest.mark.asyncio
async def test_has_blocking_dialog_true(backend):
    with patch.object(backend, "_run_cmd", side_effect=[
        ("12345", "", 0),
        ("_NET_WM_WINDOW_TYPE_DIALOG", "", 0),
        ("google chrome", "", 0),
    ]):
        result = await backend.has_blocking_dialog(["Google Chrome"])
        assert result is True

@pytest.mark.asyncio
async def test_has_blocking_dialog_false_no_window(backend):
    with patch.object(backend, "_run_cmd", side_effect=[
        ("", "", 0),
    ]):
        result = await backend.has_blocking_dialog(["Google Chrome"])
        assert result is False

@pytest.mark.asyncio
async def test_has_blocking_dialog_false_not_dialog(backend):
    with patch.object(backend, "_run_cmd", side_effect=[
        ("12345", "", 0),
        ("_NET_WM_WINDOW_TYPE_NORMAL", "", 0),
    ]):
        result = await backend.has_blocking_dialog(["Google Chrome"])
        assert result is False

@pytest.mark.asyncio
async def test_has_blocking_dialog_false_wrong_app(backend):
    with patch.object(backend, "_run_cmd", side_effect=[
        ("12345", "", 0),
        ("_NET_WM_WINDOW_TYPE_DIALOG", "", 0),
        ("firefox", "", 0),
    ]):
        result = await backend.has_blocking_dialog(["Google Chrome"])
        assert result is False

@pytest.mark.asyncio
async def test_has_blocking_dialog_exception(backend):
    with patch.object(backend, "_run_cmd", side_effect=Exception("error")):
        result = await backend.has_blocking_dialog(["Google Chrome"])
        assert result is False

@pytest.mark.asyncio
async def test_is_browser_active_true(backend):
    with patch.object(backend, "_run_cmd", side_effect=[
        ("12345", "", 0),
        ("google-chrome", "", 0),
    ]):
        result = await backend.is_browser_active()
        assert result is True

@pytest.mark.asyncio
async def test_is_browser_active_false_no_window(backend):
    with patch.object(backend, "_run_cmd", side_effect=[
        ("", "", 0),
    ]):
        result = await backend.is_browser_active()
        assert result is False

@pytest.mark.asyncio
async def test_is_browser_active_false_wrong_app(backend):
    with patch.object(backend, "_run_cmd", side_effect=[
        ("12345", "", 0),
        ("gnome-terminal", "", 0),
    ]):
        result = await backend.is_browser_active()
        assert result is False

@pytest.mark.asyncio
async def test_is_browser_active_exception(backend):
    with patch.object(backend, "_run_cmd", side_effect=Exception("error")):
        result = await backend.is_browser_active()
        assert result is False
