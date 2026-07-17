"""Tests for ComputerSession.check_foreground_permission — foreground permission gate.

Covers all 5 branch paths:
1. foreground mode → always pass through (no check)
2. cached grant (session/always) → pass through
3. no callback + background_strict → deny with error
4. no callback + background_best_effort → pass through (backward compatible)
5. callback invoked → grant (with scope caching) / deny
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.computer_use.session import ComputerSession
from myrm_agent_harness.toolkits.computer_use.types import (
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
