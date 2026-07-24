"""Tests for ComputerSession.check_foreground_permission — foreground permission gate.

Covers all 5 branch paths:
1. foreground mode → always pass through (no check)
2. cached grant (session/always) → pass through
3. no callback + background_strict → deny with error
4. no callback + background_best_effort → pass through (backward compatible)
5. callback invoked → grant (with scope caching) / deny
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.computer_use.session import ComputerSession
from myrm_agent_harness.toolkits.computer_use.types import (
    ActionResult,
    ComputerUseConfig,
    ExecutionMode,
    ForegroundPermissionResult,
    ForegroundPermissionScope,
)


@pytest.fixture
def backend() -> MagicMock:
    from myrm_agent_harness.toolkits.computer_use.types import ScreenInfo

    b = MagicMock()
    b.screen_info.return_value = ScreenInfo(width=1920, height=1080, dpi_scale=1.0)
    return b


class TestForegroundMode:
    """ExecutionMode.foreground → always pass through regardless of callback."""

    @pytest.mark.asyncio
    async def test_foreground_mode_passes_without_callback(self, backend: MagicMock) -> None:
        config = ComputerUseConfig(execution_mode=ExecutionMode.foreground)
        session = ComputerSession(backend=backend, config=config)

        result = await session.check_foreground_permission(
            reason="test", operation="click(100, 200)"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_foreground_mode_never_calls_callback(self, backend: MagicMock) -> None:
        callback = AsyncMock()
        config = ComputerUseConfig(execution_mode=ExecutionMode.foreground)
        session = ComputerSession(backend=backend, config=config, permission_callback=callback)

        await session.check_foreground_permission(reason="test", operation="click")
        callback.assert_not_called()


class TestCachedGrant:
    """Previously granted permission (session/always scope) → pass through."""

    @pytest.mark.asyncio
    async def test_session_scope_caches(self, backend: MagicMock) -> None:
        callback = AsyncMock(return_value=ForegroundPermissionResult(
            granted=True, scope=ForegroundPermissionScope.session
        ))
        config = ComputerUseConfig(execution_mode=ExecutionMode.background_strict)
        session = ComputerSession(backend=backend, config=config, permission_callback=callback)

        first = await session.check_foreground_permission(reason="first", operation="op1")
        assert first is None
        assert callback.call_count == 1

        second = await session.check_foreground_permission(reason="second", operation="op2")
        assert second is None
        assert callback.call_count == 1  # not called again

    @pytest.mark.asyncio
    async def test_always_scope_caches(self, backend: MagicMock) -> None:
        callback = AsyncMock(return_value=ForegroundPermissionResult(
            granted=True, scope=ForegroundPermissionScope.always
        ))
        config = ComputerUseConfig(execution_mode=ExecutionMode.background_best_effort)
        session = ComputerSession(backend=backend, config=config, permission_callback=callback)

        await session.check_foreground_permission(reason="first", operation="op1")
        await session.check_foreground_permission(reason="second", operation="op2")
        assert callback.call_count == 1


class TestNoCallback:
    """No permission callback configured — behavior depends on mode."""

    @pytest.mark.asyncio
    async def test_strict_mode_denies(self, backend: MagicMock) -> None:
        config = ComputerUseConfig(execution_mode=ExecutionMode.background_strict)
        session = ComputerSession(backend=backend, config=config, permission_callback=None)

        result = await session.check_foreground_permission(
            reason="need foreground", operation="bbox_click"
        )
        assert result is not None
        assert result.success is False
        assert "background_strict" in result.error

    @pytest.mark.asyncio
    async def test_best_effort_mode_passes(self, backend: MagicMock) -> None:
        config = ComputerUseConfig(execution_mode=ExecutionMode.background_best_effort)
        session = ComputerSession(backend=backend, config=config, permission_callback=None)

        result = await session.check_foreground_permission(
            reason="need foreground", operation="bbox_click"
        )
        assert result is None


class TestCallbackInvocation:
    """Callback invoked — grant vs deny."""

    @pytest.mark.asyncio
    async def test_callback_deny_returns_error(self, backend: MagicMock) -> None:
        callback = AsyncMock(return_value=ForegroundPermissionResult(granted=False))
        config = ComputerUseConfig(execution_mode=ExecutionMode.background_strict)
        session = ComputerSession(backend=backend, config=config, permission_callback=callback)

        result = await session.check_foreground_permission(
            reason="AX failed", operation="click(50, 60)"
        )
        assert result is not None
        assert result.success is False
        assert "denied" in result.error.lower()

    @pytest.mark.asyncio
    async def test_callback_grant_once_does_not_cache(self, backend: MagicMock) -> None:
        callback = AsyncMock(return_value=ForegroundPermissionResult(
            granted=True, scope=ForegroundPermissionScope.once
        ))
        config = ComputerUseConfig(execution_mode=ExecutionMode.background_strict)
        session = ComputerSession(backend=backend, config=config, permission_callback=callback)

        await session.check_foreground_permission(reason="first", operation="op1")
        await session.check_foreground_permission(reason="second", operation="op2")
        assert callback.call_count == 2  # called each time (no caching for 'once')

    @pytest.mark.asyncio
    async def test_callback_receives_correct_args(self, backend: MagicMock) -> None:
        callback = AsyncMock(return_value=ForegroundPermissionResult(
            granted=True, scope=ForegroundPermissionScope.once
        ))
        config = ComputerUseConfig(execution_mode=ExecutionMode.background_best_effort)
        session = ComputerSession(backend=backend, config=config, permission_callback=callback)

        await session.check_foreground_permission(
            reason="AX invoke failed",
            operation="bbox_click(320, 480)",
            estimated_duration_seconds=3.0,
        )
        callback.assert_called_once_with(
            reason="AX invoke failed",
            operation="bbox_click(320, 480)",
            estimated_duration_seconds=3.0,
            app_name="",
            window_title="",
            require_app_approval=False,
        )


class TestResetRuntimePermissionCache:
    def test_clears_session_flags(self, backend: MagicMock) -> None:
        session = ComputerSession(backend=backend, config=ComputerUseConfig())
        session._session_permission_granted = True
        session._always_permission_granted = True
        session._operation_foreground_waived = True

        session.reset_runtime_permission_cache()

        assert session._session_permission_granted is False
        assert session._always_permission_granted is False
        assert session._operation_foreground_waived is False


class TestCheckAppApproval:
    """check_app_approval: per-app gate with inspect_backend fallback."""

    @pytest.mark.asyncio
    async def test_inspect_fallback_when_app_name_empty(self, backend: MagicMock) -> None:
        from unittest.mock import patch

        callback = AsyncMock(
            return_value=ForegroundPermissionResult(granted=True, scope=ForegroundPermissionScope.once)
        )
        config = ComputerUseConfig(execution_mode=ExecutionMode.background_strict)
        session = ComputerSession(backend=backend, config=config, permission_callback=callback)

        with patch(
            "myrm_agent_harness.toolkits.computer_use.perception.ax_dispatch.inspect_backend",
            return_value={"app_name": "Finder", "window_title": "Desktop"},
        ):
            result = await session.check_app_approval(
                app_name="",
                window_title="",
                operation="desktop_interact(click, @d1)",
            )

        assert result is None
        callback.assert_called_once()
        assert callback.call_args.kwargs["app_name"] == "Finder"
        assert callback.call_args.kwargs["window_title"] == "Desktop"

    @pytest.mark.asyncio
    async def test_fail_closed_when_foreground_unknown(self, backend: MagicMock) -> None:
        from unittest.mock import patch

        callback = AsyncMock(return_value=ForegroundPermissionResult(granted=True))
        config = ComputerUseConfig(execution_mode=ExecutionMode.background_strict)
        session = ComputerSession(backend=backend, config=config, permission_callback=callback)

        with patch(
            "myrm_agent_harness.toolkits.computer_use.perception.ax_dispatch.inspect_backend",
            return_value={"app_name": "", "window_title": ""},
        ):
            result = await session.check_app_approval(
                app_name="",
                window_title="",
                operation="desktop_interact(click, @d1)",
            )

        assert result is not None
        assert result.success is False
        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_app_best_effort_without_callback_passes(self, backend: MagicMock) -> None:
        from unittest.mock import patch

        config = ComputerUseConfig(execution_mode=ExecutionMode.background_best_effort)
        session = ComputerSession(backend=backend, config=config, permission_callback=None)

        with patch(
            "myrm_agent_harness.toolkits.computer_use.perception.ax_dispatch.inspect_backend",
            return_value={"app_name": "", "window_title": ""},
        ):
            result = await session.check_app_approval(
                app_name="",
                window_title="",
                operation="desktop_interact(click, @d1)",
            )

        assert result is None


    @pytest.mark.asyncio
    async def test_app_approval_denied_by_callback(self, backend: MagicMock) -> None:
        callback = AsyncMock(return_value=ForegroundPermissionResult(granted=False))
        config = ComputerUseConfig(execution_mode=ExecutionMode.background_strict)
        session = ComputerSession(backend=backend, config=config, permission_callback=callback)

        result = await session.check_app_approval(
            app_name="Notes",
            window_title="Memo",
            operation="desktop_interact(click, @d1)",
        )

        assert result is not None
        assert result.success is False
        assert "Notes" in result.error
        assert session._operation_foreground_waived is False

    @pytest.mark.asyncio
    async def test_app_approval_no_callback_strict_with_app(self, backend: MagicMock) -> None:
        config = ComputerUseConfig(execution_mode=ExecutionMode.background_strict)
        session = ComputerSession(backend=backend, config=config, permission_callback=None)

        result = await session.check_app_approval(
            app_name="Finder",
            window_title="Desktop",
            operation="desktop_interact(click, @d1)",
        )

        assert result is not None
        assert result.success is False
        assert "no permission callback" in result.error


class TestOperationForegroundWaiver:
    """App approval grants a one-shot foreground waiver for bbox/healer in the same tool call."""

    @pytest.mark.asyncio
    async def test_app_approval_waives_immediate_foreground_check(self, backend: MagicMock) -> None:
        callback = AsyncMock(
            return_value=ForegroundPermissionResult(granted=True, scope=ForegroundPermissionScope.once),
        )
        config = ComputerUseConfig(execution_mode=ExecutionMode.background_strict)
        session = ComputerSession(backend=backend, config=config, permission_callback=callback)

        app_result = await session.check_app_approval(
            app_name="Finder",
            window_title="Desktop",
            operation="desktop_interact(click, @d1)",
        )
        assert app_result is None
        assert callback.call_count == 1

        fg_result = await session.check_foreground_permission(
            reason="bbox fallback",
            operation="bbox_click(100, 200)",
            app_name="Finder",
            window_title="Desktop",
        )
        assert fg_result is None
        assert callback.call_count == 1

        session.clear_operation_foreground_waiver()
        await session.check_foreground_permission(
            reason="bbox fallback again",
            operation="bbox_click(100, 200)",
        )
        assert callback.call_count == 2

    @pytest.mark.asyncio
    async def test_app_approval_always_scope_caches_foreground(self, backend: MagicMock) -> None:
        callback = AsyncMock(
            return_value=ForegroundPermissionResult(
                granted=True, scope=ForegroundPermissionScope.always
            )
        )
        config = ComputerUseConfig(execution_mode=ExecutionMode.background_strict)
        session = ComputerSession(backend=backend, config=config, permission_callback=callback)

        app_result = await session.check_app_approval(
            app_name="Finder",
            window_title="Desktop",
            operation="desktop_interact(click, @d1)",
        )
        assert app_result is None
        assert callback.call_count == 1

        session.clear_operation_foreground_waiver()
        fg_result = await session.check_foreground_permission(
            reason="bbox fallback",
            operation="bbox_click(100, 200)",
        )
        assert fg_result is None
        assert callback.call_count == 1


class TestComputerSessionCoordinateIo:
    """Cover coordinate I/O helpers in session.py for SDC vision fallback paths."""

    @pytest.fixture
    def backend(self) -> MagicMock:
        from myrm_agent_harness.toolkits.computer_use.types import ScreenInfo

        b = MagicMock()
        b.screen_info.return_value = ScreenInfo(width=1920, height=1080, dpi_scale=1.0)
        b.screenshot = AsyncMock(return_value=b"\x89PNG\r\n")
        b.click = AsyncMock(return_value=ActionResult(success=True))
        b.type_text = AsyncMock(return_value=ActionResult(success=True))
        b.key = AsyncMock(return_value=ActionResult(success=True))
        b.mouse_move = AsyncMock(return_value=ActionResult(success=True))
        b.scroll = AsyncMock(return_value=ActionResult(success=True))
        b.drag = AsyncMock(return_value=ActionResult(success=True))
        b.wait = AsyncMock(return_value=ActionResult(success=True))
        b.close = AsyncMock(side_effect=RuntimeError("close failed"))
        return b

    @pytest.fixture
    def session(self, backend: MagicMock) -> ComputerSession:
        from myrm_agent_harness.toolkits.computer_use.coordinate_scaler import CoordinateScaler

        s = ComputerSession(backend=backend, config=ComputerUseConfig(screenshot_delay=0.0))
        s._scaler = CoordinateScaler(
            screen_width=1920,
            screen_height=1080,
            sent_width=800,
            sent_height=600,
            dpi_scale=1.0,
        )
        return s

    @pytest.mark.asyncio
    async def test_click_at_rejects_out_of_bounds(self, session: ComputerSession) -> None:
        result = await session.click_at(900, 700)
        assert result.success is False
        assert "out of bounds" in (result.error or "")

    @pytest.mark.asyncio
    async def test_zoom_region_returns_crop(self, session: ComputerSession, backend: MagicMock) -> None:
        with patch.object(session._processor, "crop_and_process", return_value=("b64crop", (200, 200))):
            result = await session.zoom_region(100, 100, size=400)
        assert result.success is True
        assert result.screenshot_base64 == "b64crop"
        backend.screenshot.assert_awaited()

    @pytest.mark.asyncio
    async def test_type_text_and_key_press_refresh_screenshot(self, session: ComputerSession) -> None:
        with patch.object(session, "take_screenshot", new_callable=AsyncMock) as mock_ss:
            mock_ss.return_value = ActionResult(
                success=True, screenshot_base64="ss", screenshot_size=(800, 600)
            )
            typed = await session.type_text("hello")
            keyed = await session.key_press("Return")
        assert typed.success is True
        assert keyed.success is True
        assert typed.screenshot_base64 == "ss"

    @pytest.mark.asyncio
    async def test_mouse_move_scroll_drag(self, session: ComputerSession, backend: MagicMock) -> None:
        with patch.object(session, "take_screenshot", new_callable=AsyncMock) as mock_ss:
            mock_ss.return_value = ActionResult(
                success=True, screenshot_base64="ss", screenshot_size=(800, 600)
            )
            await session.mouse_move_to(10, 20)
            await session.scroll_at(10, 20, "down", 2)
            await session.drag(0, 0, 50, 50)
        backend.mouse_move.assert_awaited_once()
        backend.scroll.assert_awaited_once()
        backend.drag.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_wait_seconds_and_close_non_fatal(self, session: ComputerSession) -> None:
        with patch.object(session, "take_screenshot", new_callable=AsyncMock) as mock_ss:
            mock_ss.return_value = ActionResult(
                success=True, screenshot_base64="ss", screenshot_size=(800, 600)
            )
            waited = await session.wait_seconds(0.01)
        assert waited.screenshot_base64 == "ss"
        await session.close()

    @pytest.mark.asyncio
    async def test_lazy_scaler_init_for_mouse_scroll_drag(self, backend: MagicMock) -> None:
        session = ComputerSession(backend=backend, config=ComputerUseConfig(screenshot_delay=0.0))
        assert session.scaler is None

        with patch.object(session._processor, "process", return_value=("b64", (800, 600))):
            await session.mouse_move_to(10, 20)

        assert session.scaler is not None
        backend.mouse_move.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_scroll_at_lazy_scaler_init(self, backend: MagicMock) -> None:
        session = ComputerSession(backend=backend, config=ComputerUseConfig(screenshot_delay=0.0))
        with patch.object(session._processor, "process", return_value=("b64", (800, 600))):
            await session.scroll_at(10, 20, "down", 2)
        backend.scroll.assert_awaited_once()
        assert session.scaler is not None

    @pytest.mark.asyncio
    async def test_drag_lazy_scaler_init(self, backend: MagicMock) -> None:
        session = ComputerSession(backend=backend, config=ComputerUseConfig(screenshot_delay=0.0))
        with patch.object(session._processor, "process", return_value=("b64", (800, 600))):
            await session.drag(0, 0, 50, 50)
        backend.drag.assert_awaited_once()
        assert session.scaler is not None

    @pytest.mark.asyncio
    async def test_check_permissions_delegates_to_backend(self, backend: MagicMock) -> None:
        from myrm_agent_harness.toolkits.computer_use.types import PermissionStatus

        expected = PermissionStatus(accessibility=True, screen_recording=True)
        backend.check_permissions = AsyncMock(return_value=expected)
        session = ComputerSession(backend=backend, config=ComputerUseConfig())
        result = await session.check_permissions()
        assert result is expected

    @pytest.mark.asyncio
    async def test_zoom_region_lazy_scaler_init(self, backend: MagicMock) -> None:
        session = ComputerSession(backend=backend, config=ComputerUseConfig(screenshot_delay=0.0))
        with patch.object(session._processor, "process", return_value=("b64", (800, 600))):
            with patch.object(session._processor, "crop_and_process", return_value=("b64crop", (200, 200))):
                result = await session.zoom_region(100, 100, size=400)
        assert result.success is True
        assert session.scaler is not None


class TestComputerSessionProperties:
    def test_scaler_initially_none(self, backend: MagicMock) -> None:
        session = ComputerSession(backend=backend, config=ComputerUseConfig())
        assert session.scaler is None

    def test_screen_context_delegates_to_backend(self, backend: MagicMock) -> None:
        from myrm_agent_harness.toolkits.computer_use.types import ScreenContext

        expected = ScreenContext(active_window="Finder", mouse_x=10, mouse_y=20)
        backend.screen_context.return_value = expected
        session = ComputerSession(backend=backend, config=ComputerUseConfig())
        assert session.screen_context is expected


class TestCreateComputerSession:
    def test_create_session_macos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from myrm_agent_harness.toolkits.computer_use import session as session_module

        class FakePlatform:
            os_type = "macos"

        fake_backend = MagicMock()
        monkeypatch.setattr(
            "myrm_agent_harness.toolkits.code_execution.platform.detect_platform",
            lambda: FakePlatform(),
        )
        monkeypatch.setattr(
            "myrm_agent_harness.toolkits.computer_use.backends.macos.MacOSBackend",
            lambda: fake_backend,
        )
        monkeypatch.setattr(session_module, "_try_wrap_with_cua_driver", lambda backend: backend)

        created = session_module.create_computer_session()
        assert isinstance(created, ComputerSession)
        assert created._backend is fake_backend

    def test_try_wrap_uses_cua_when_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from myrm_agent_harness.toolkits.computer_use import session as session_module

        native = MagicMock()
        wrapped = MagicMock()
        monkeypatch.setattr(
            "myrm_agent_harness.toolkits.computer_use.backends.cua_driver.is_cua_driver_available",
            lambda: True,
        )
        monkeypatch.setattr(
            "myrm_agent_harness.toolkits.computer_use.backends.cua_driver.CuaDriverBackend",
            lambda *, fallback: wrapped,
        )
        assert session_module._try_wrap_with_cua_driver(native) is wrapped

    def test_try_wrap_returns_native_when_cua_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from myrm_agent_harness.toolkits.computer_use import session as session_module

        native = MagicMock()
        monkeypatch.setattr(
            "myrm_agent_harness.toolkits.computer_use.backends.cua_driver.is_cua_driver_available",
            lambda: False,
        )
        assert session_module._try_wrap_with_cua_driver(native) is native

    def test_try_wrap_import_error_returns_native(self) -> None:
        from myrm_agent_harness.toolkits.computer_use import session as session_module

        native = MagicMock()
        with patch(
            "myrm_agent_harness.toolkits.computer_use.backends.cua_driver.is_cua_driver_available",
            side_effect=ImportError("missing mcp sdk"),
        ):
            assert session_module._try_wrap_with_cua_driver(native) is native
