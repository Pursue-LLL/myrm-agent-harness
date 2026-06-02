"""Tests for modifier-key mouse actions across all layers.

Covers:
- ModifierKey type definition and values
- MacOSBackend: modifier keyDown/keyUp with try/finally guarantee
- LinuxBackend: modifier keydown/keyup with try/finally guarantee
- ComputerSession: modifier pass-through to backend
- ActionInput schema: modifiers field validation
"""

from __future__ import annotations

from typing import get_args
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.computer_use.types import ActionResult, ModifierKey


class TestModifierKeyType:
    """ModifierKey Literal type correctness."""

    def test_modifier_key_values(self) -> None:
        allowed = get_args(ModifierKey)
        assert set(allowed) == {"ctrl", "shift", "alt", "meta"}

    def test_modifier_key_is_literal(self) -> None:
        from typing import Literal, get_origin
        assert get_origin(ModifierKey) is Literal


def _mock_pyautogui() -> MagicMock:
    """Create a fully mocked pyautogui with named functions for test introspection."""
    m = MagicMock()
    m.size.return_value = MagicMock(width=1920, height=1080)
    m.position.return_value = MagicMock(x=0, y=0)
    for name in ("keyDown", "keyUp", "click", "scroll", "hscroll", "moveTo", "drag", "write", "press", "hotkey"):
        fn = MagicMock()
        fn.__name__ = name
        setattr(m, name, fn)
    return m


_MACOS_MOCK_MODULES = {
    "AppKit": MagicMock(),
    "rubicon": MagicMock(),
    "rubicon.objc": MagicMock(),
    "rubicon.objc.api": MagicMock(),
    "rubicon.objc.runtime": MagicMock(),
    "rubicon.objc.collections": MagicMock(),
    "rubicon.objc.types": MagicMock(),
    "Quartz": MagicMock(),
    "Quartz.CoreGraphics": MagicMock(),
    "mouseinfo": MagicMock(),
}


@pytest.fixture
def _mock_macos_env():
    """Fixture to mock all macOS-specific modules for the entire test lifetime."""
    mock_pyautogui = _mock_pyautogui()
    modules = {**_MACOS_MOCK_MODULES, "pyautogui": mock_pyautogui}
    with patch.dict("sys.modules", modules):
        import importlib

        import myrm_agent_harness.toolkits.computer_use.backends.macos as macos_mod
        importlib.reload(macos_mod)
        yield macos_mod


@pytest.mark.usefixtures("_mock_macos_env")
class TestMacOSBackendModifiers:
    """MacOSBackend modifier key handling with pyautogui mock."""

    @pytest.fixture
    def backend(self, _mock_macos_env):
        return _mock_macos_env.MacOSBackend()

    @pytest.mark.asyncio
    async def test_click_with_modifiers_calls_key_down_and_up(self, backend) -> None:
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
    async def test_click_without_modifiers_no_keydown(self, backend) -> None:
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
        """Verify try/finally guarantees keyUp even when action throws."""
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
        assert call_log[names.index("keyDown")][1] == ("ctrl",)

    @pytest.mark.asyncio
    async def test_drag_with_modifiers(self, backend) -> None:
        call_log: list[tuple[str, tuple]] = []

        async def mock_to_thread(fn, *args, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            call_log.append((name, args))
            return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            result = await backend.drag(100, 200, 300, 400, modifiers=["alt"])

        assert result.success is True
        names = [c[0] for c in call_log]
        assert names.count("keyDown") == 1
        assert names.count("keyUp") == 1
        assert call_log[names.index("keyDown")][1] == ("option",)
        assert call_log[names.index("keyUp")][1] == ("option",)

    @pytest.mark.asyncio
    async def test_meta_maps_to_command(self, backend) -> None:
        call_log: list[tuple[str, tuple]] = []

        async def mock_to_thread(fn, *args, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            call_log.append((name, args))
            return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            await backend.click(100, 200, modifiers=["meta"])

        names = [c[0] for c in call_log]
        keydown_idx = names.index("keyDown")
        assert call_log[keydown_idx][1] == ("command",)


class TestLinuxBackendModifiers:
    """LinuxBackend modifier key handling with xdotool mock."""

    @pytest.fixture
    def backend(self):
        from myrm_agent_harness.toolkits.computer_use.backends.linux import LinuxBackend
        return LinuxBackend(display_num=99)

    @pytest.mark.asyncio
    async def test_click_with_modifiers(self, backend) -> None:
        commands: list[str] = []

        async def mock_run_cmd(cmd: str):
            commands.append(cmd)
            return ("", "", 0)

        with patch.object(backend, "_run_cmd", side_effect=mock_run_cmd):
            result = await backend.click(100, 200, modifiers=["ctrl", "shift"])

        assert result.success is True
        assert any("keydown ctrl" in c for c in commands)
        assert any("keydown shift" in c for c in commands)
        assert any("keyup shift" in c for c in commands)
        assert any("keyup ctrl" in c for c in commands)

        keydown_ctrl_idx = next(i for i, c in enumerate(commands) if "keydown ctrl" in c)
        keydown_shift_idx = next(i for i, c in enumerate(commands) if "keydown shift" in c)
        click_idx = next(i for i, c in enumerate(commands) if "click" in c and "keydown" not in c and "keyup" not in c)
        keyup_shift_idx = next(i for i, c in enumerate(commands) if "keyup shift" in c)
        keyup_ctrl_idx = next(i for i, c in enumerate(commands) if "keyup ctrl" in c)

        assert keydown_ctrl_idx < keydown_shift_idx < click_idx < keyup_shift_idx < keyup_ctrl_idx

    @pytest.mark.asyncio
    async def test_click_without_modifiers_no_keydown(self, backend) -> None:
        commands: list[str] = []

        async def mock_run_cmd(cmd: str):
            commands.append(cmd)
            return ("", "", 0)

        with patch.object(backend, "_run_cmd", side_effect=mock_run_cmd):
            result = await backend.click(100, 200)

        assert result.success is True
        assert not any("keydown" in c for c in commands)
        assert not any("keyup" in c for c in commands)

    @pytest.mark.asyncio
    async def test_click_exception_releases_modifiers(self, backend) -> None:
        """Verify try/finally guarantees keyup even when action throws."""
        commands: list[str] = []

        async def mock_run_cmd(cmd: str):
            commands.append(cmd)
            if "click" in cmd and "keydown" not in cmd and "keyup" not in cmd:
                raise RuntimeError("simulated xdotool failure")
            return ("", "", 0)

        with patch.object(backend, "_run_cmd", side_effect=mock_run_cmd):
            result = await backend.click(100, 200, modifiers=["ctrl"])

        assert result.success is False
        assert any("keydown ctrl" in c for c in commands)
        assert any("keyup ctrl" in c for c in commands)

    @pytest.mark.asyncio
    async def test_scroll_with_modifiers(self, backend) -> None:
        commands: list[str] = []

        async def mock_run_cmd(cmd: str):
            commands.append(cmd)
            return ("", "", 0)

        with patch.object(backend, "_run_cmd", side_effect=mock_run_cmd):
            result = await backend.scroll(100, 200, "up", 2, modifiers=["ctrl"])

        assert result.success is True
        assert any("keydown ctrl" in c for c in commands)
        assert any("keyup ctrl" in c for c in commands)

    @pytest.mark.asyncio
    async def test_drag_with_modifiers(self, backend) -> None:
        commands: list[str] = []

        async def mock_run_cmd(cmd: str):
            commands.append(cmd)
            return ("", "", 0)

        with patch.object(backend, "_run_cmd", side_effect=mock_run_cmd):
            result = await backend.drag(10, 20, 100, 200, modifiers=["alt"])

        assert result.success is True
        assert any("keydown alt" in c for c in commands)
        assert any("keyup alt" in c for c in commands)

    @pytest.mark.asyncio
    async def test_meta_maps_to_super(self, backend) -> None:
        commands: list[str] = []

        async def mock_run_cmd(cmd: str):
            commands.append(cmd)
            return ("", "", 0)

        with patch.object(backend, "_run_cmd", side_effect=mock_run_cmd):
            await backend.click(100, 200, modifiers=["meta"])

        assert any("keydown super" in c for c in commands)
        assert any("keyup super" in c for c in commands)


class TestSessionModifierPassthrough:
    """ComputerSession passes modifiers to backend."""

    @pytest.fixture
    def mock_backend(self):
        backend = AsyncMock()
        from myrm_agent_harness.toolkits.computer_use.types import ScreenContext, ScreenInfo
        backend.screen_info.return_value = ScreenInfo(width=1920, height=1080, dpi_scale=1.0)
        backend.screen_context.return_value = ScreenContext(active_window="test", mouse_x=0, mouse_y=0)
        backend.click.return_value = ActionResult(success=True)
        backend.scroll.return_value = ActionResult(success=True)
        backend.drag.return_value = ActionResult(success=True)
        return backend

    @pytest.fixture
    def session(self, mock_backend):
        from myrm_agent_harness.toolkits.computer_use.coordinate_scaler import CoordinateScaler
        from myrm_agent_harness.toolkits.computer_use.session import ComputerSession
        from myrm_agent_harness.toolkits.computer_use.types import ComputerUseConfig
        s = ComputerSession(backend=mock_backend, config=ComputerUseConfig())
        s._scaler = CoordinateScaler(
            screen_width=1920, screen_height=1080,
            sent_width=1920, sent_height=1080, dpi_scale=1.0,
        )
        return s

    @pytest.mark.asyncio
    async def test_click_at_passes_modifiers(self, session, mock_backend) -> None:
        with patch.object(session, "take_screenshot", new_callable=AsyncMock) as mock_ss:
            mock_ss.return_value = ActionResult(success=True, screenshot_base64="abc", screenshot_size=(1920, 1080))
            await session.click_at(100, 200, modifiers=["ctrl"])

        mock_backend.click.assert_called_once()
        _, kwargs = mock_backend.click.call_args
        assert kwargs.get("modifiers") == ["ctrl"]

    @pytest.mark.asyncio
    async def test_scroll_at_passes_modifiers(self, session, mock_backend) -> None:
        with patch.object(session, "take_screenshot", new_callable=AsyncMock) as mock_ss:
            mock_ss.return_value = ActionResult(success=True, screenshot_base64="abc", screenshot_size=(1920, 1080))
            await session.scroll_at(100, 200, "down", 3, modifiers=["shift"])

        mock_backend.scroll.assert_called_once()
        _, kwargs = mock_backend.scroll.call_args
        assert kwargs.get("modifiers") == ["shift"]

    @pytest.mark.asyncio
    async def test_drag_passes_modifiers(self, session, mock_backend) -> None:
        with patch.object(session, "take_screenshot", new_callable=AsyncMock) as mock_ss:
            mock_ss.return_value = ActionResult(success=True, screenshot_base64="abc", screenshot_size=(1920, 1080))
            await session.drag(10, 20, 100, 200, modifiers=["alt"])

        mock_backend.drag.assert_called_once()
        _, kwargs = mock_backend.drag.call_args
        assert kwargs.get("modifiers") == ["alt"]


class TestActionInputSchema:
    """ActionInput Pydantic schema includes modifiers field."""

    def test_modifiers_field_exists(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.desktop_agent_tools import create_desktop_tools
        from myrm_agent_harness.toolkits.computer_use.desktop_session import DesktopSession
        mock_session = MagicMock(spec=DesktopSession)
        tools = create_desktop_tools(mock_session)
        action_tool = next(t for t in tools if t.name == "desktop_vision_tool")
        schema = action_tool.args_schema.model_json_schema()
        assert "modifiers" in schema["properties"]
        modifiers_schema = schema["properties"]["modifiers"]
        assert modifiers_schema.get("default") is None

    def test_modifiers_field_accepts_valid_values(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.desktop_agent_tools import create_desktop_tools
        from myrm_agent_harness.toolkits.computer_use.desktop_session import DesktopSession
        mock_session = MagicMock(spec=DesktopSession)
        tools = create_desktop_tools(mock_session)
        action_tool = next(t for t in tools if t.name == "desktop_vision_tool")
        schema_cls = action_tool.args_schema
        instance = schema_cls(
            action="left_click",
            coordinate=[100, 200],
            modifiers=["ctrl", "shift"],
        )
        assert instance.modifiers == ["ctrl", "shift"]

    def test_modifiers_field_optional(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.desktop_agent_tools import create_desktop_tools
        from myrm_agent_harness.toolkits.computer_use.desktop_session import DesktopSession
        mock_session = MagicMock(spec=DesktopSession)
        tools = create_desktop_tools(mock_session)
        action_tool = next(t for t in tools if t.name == "desktop_vision_tool")
        schema_cls = action_tool.args_schema
        instance = schema_cls(action="left_click", coordinate=[100, 200])
        assert instance.modifiers is None


@pytest.mark.usefixtures("_mock_macos_env")
class TestEdgeCases:
    """Edge cases for modifier key handling."""

    @pytest.fixture
    def linux_backend(self):
        from myrm_agent_harness.toolkits.computer_use.backends.linux import LinuxBackend
        return LinuxBackend(display_num=99)

    @pytest.fixture
    def macos_backend(self, _mock_macos_env):
        return _mock_macos_env.MacOSBackend()

    @pytest.mark.asyncio
    async def test_empty_list_modifiers_no_keydown(self, linux_backend) -> None:
        """Empty list [] behaves same as None — no keydown/keyup calls."""
        commands: list[str] = []

        async def mock_run_cmd(cmd: str):
            commands.append(cmd)
            return ("", "", 0)

        with patch.object(linux_backend, "_run_cmd", side_effect=mock_run_cmd):
            result = await linux_backend.click(100, 200, modifiers=[])

        assert result.success is True
        assert not any("keydown" in c for c in commands)
        assert not any("keyup" in c for c in commands)

    @pytest.mark.asyncio
    async def test_three_modifiers_all_pressed_and_released(self, linux_backend) -> None:
        """Triple modifier combo: all pressed in order, released in reverse."""
        commands: list[str] = []

        async def mock_run_cmd(cmd: str):
            commands.append(cmd)
            return ("", "", 0)

        with patch.object(linux_backend, "_run_cmd", side_effect=mock_run_cmd):
            result = await linux_backend.click(100, 200, modifiers=["ctrl", "alt", "shift"])

        assert result.success is True
        keydowns = [c for c in commands if "keydown" in c]
        keyups = [c for c in commands if "keyup" in c]
        assert len(keydowns) == 3
        assert len(keyups) == 3
        assert "keydown ctrl" in keydowns[0]
        assert "keydown alt" in keydowns[1]
        assert "keydown shift" in keydowns[2]
        assert "keyup shift" in keyups[0]
        assert "keyup alt" in keyups[1]
        assert "keyup ctrl" in keyups[2]

    @pytest.mark.asyncio
    async def test_scroll_exception_releases_modifiers(self, linux_backend) -> None:
        """Scroll action failure still releases modifier keys."""
        commands: list[str] = []
        call_count = 0

        async def mock_run_cmd(cmd: str):
            nonlocal call_count
            commands.append(cmd)
            call_count += 1
            if "click" in cmd and "keydown" not in cmd and "keyup" not in cmd:
                raise RuntimeError("scroll button click failed")
            return ("", "", 0)

        with patch.object(linux_backend, "_run_cmd", side_effect=mock_run_cmd):
            result = await linux_backend.scroll(100, 200, "down", 1, modifiers=["ctrl"])

        assert result.success is False
        assert any("keydown ctrl" in c for c in commands)
        assert any("keyup ctrl" in c for c in commands)

    @pytest.mark.asyncio
    async def test_drag_exception_releases_modifiers(self, linux_backend) -> None:
        """Drag action failure still releases modifier keys."""
        commands: list[str] = []

        async def mock_run_cmd(cmd: str):
            commands.append(cmd)
            if "mousemove" in cmd and "mousedown" in cmd:
                raise RuntimeError("drag command failed")
            return ("", "", 0)

        with patch.object(linux_backend, "_run_cmd", side_effect=mock_run_cmd):
            result = await linux_backend.drag(10, 20, 100, 200, modifiers=["shift"])

        assert result.success is False
        assert any("keydown shift" in c for c in commands)
        assert any("keyup shift" in c for c in commands)

    @pytest.mark.asyncio
    async def test_macos_scroll_exception_releases_modifiers(self, macos_backend) -> None:
        """macOS scroll action failure still releases modifier keys."""
        call_log: list[tuple[str, tuple]] = []

        async def mock_to_thread(fn, *args, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            call_log.append((name, args))
            if name == "scroll":
                raise RuntimeError("scroll failed")
            return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            result = await macos_backend.scroll(100, 200, "down", 3, modifiers=["ctrl"])

        assert result.success is False
        names = [c[0] for c in call_log]
        assert "keyDown" in names
        assert "keyUp" in names

    @pytest.mark.asyncio
    async def test_macos_drag_exception_releases_modifiers(self, macos_backend) -> None:
        """macOS drag action failure still releases modifier keys."""
        call_log: list[tuple[str, tuple]] = []

        async def mock_to_thread(fn, *args, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            call_log.append((name, args))
            if name == "moveTo":
                raise RuntimeError("drag failed")
            return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            result = await macos_backend.drag(10, 20, 100, 200, modifiers=["alt"])

        assert result.success is False
        names = [c[0] for c in call_log]
        assert "keyDown" in names
        assert "keyUp" in names

    @pytest.mark.asyncio
    async def test_macos_empty_list_modifiers_no_keydown(self, macos_backend) -> None:
        """macOS: Empty list [] behaves same as None — no keydown/keyup calls."""
        call_log: list[tuple[str, tuple]] = []

        async def mock_to_thread(fn, *args, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            call_log.append((name, args))
            return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            result = await macos_backend.click(100, 200, modifiers=[])

        assert result.success is True
        names = [c[0] for c in call_log]
        assert "keyDown" not in names
        assert "keyUp" not in names
