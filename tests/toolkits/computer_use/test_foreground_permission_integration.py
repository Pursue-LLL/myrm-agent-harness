"""Integration tests for foreground permission gate.

Exercises the REAL integration paths:
  desktop_vision_action → is_foreground_required → check_foreground_permission → callback
  try_bbox_click → check_foreground_permission → callback

Only the hardware backend and platform-specific AX layer are mocked (no real screen).
The session, safety module, and permission logic are NOT mocked — this validates
the full chain works end-to-end within the harness.
"""

from __future__ import annotations

import io
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from myrm_agent_harness.toolkits.computer_use.desktop_session import DesktopSession
from myrm_agent_harness.toolkits.computer_use.execution.healer import try_bbox_click
from myrm_agent_harness.toolkits.computer_use.types import (
    ActionResult,
    ComputerUseConfig,
    ExecutionMode,
    ForegroundPermissionResult,
    ForegroundPermissionScope,
    ScreenInfo,
)
from myrm_agent_harness.toolkits.computer_use.dref.types import BBox, ElementRef


def _realistic_png_bytes() -> bytes:
    """Generate a 1920x1080 noisy PNG that passes the min-size check after JPEG encoding."""
    import random
    random.seed(42)
    img = Image.new("RGB", (1920, 1080))
    pixels = img.load()
    for y in range(0, 1080, 10):
        for x in range(0, 1920, 10):
            c = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
            for dy in range(min(10, 1080 - y)):
                for dx in range(min(10, 1920 - x)):
                    pixels[x + dx, y + dy] = c
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


_FAKE_SCREENSHOT = _realistic_png_bytes()


def _make_backend() -> MagicMock:
    """Create a fake backend with minimal screen info and async methods."""
    b = MagicMock()
    b.screen_info.return_value = ScreenInfo(width=1920, height=1080, dpi_scale=1.0)
    b.screenshot = AsyncMock(return_value=_FAKE_SCREENSHOT)
    b.click = AsyncMock(return_value=ActionResult(success=True, output="clicked"))
    b.type_text = AsyncMock(return_value=ActionResult(success=True, output="typed"))
    return b


def _make_element(x: int = 100, y: int = 200) -> ElementRef:
    return ElementRef(
        ref_id="e0",
        role="button",
        name="Submit",
        bbox=BBox(x=x, y=y, width=40, height=20),
        backend_key="ax_key_0",
    )


_NON_SENSITIVE_FG_INFO: dict[str, str | int | bool] = {
    "app_name": "Safari",
    "window_title": "Example Page",
    "interactive_estimate": 5,
    "needs_permission": False,
}


class TestDesktopVisionActionPermissionIntegration:
    """Integration: desktop_vision_action full-path permission checks."""

    @pytest.mark.asyncio
    async def test_foreground_mode_proceeds_to_action(self) -> None:
        """In foreground mode, permission gate is skipped entirely — action executes."""
        backend = _make_backend()
        config = ComputerUseConfig(
            execution_mode=ExecutionMode.foreground, screenshot_delay=0.0
        )
        session = DesktopSession(backend=backend, config=config)
        session._last_snapshot_time = time.time()

        with patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.inspect_backend",
            return_value=_NON_SENSITIVE_FG_INFO,
        ):
            result = await session.desktop_vision_action(
                action="left_click", coordinate=[50, 50]
            )

        assert "permission denied" not in str(result).lower()
        backend.click.assert_called_once()

    @pytest.mark.asyncio
    async def test_background_strict_blocks_without_callback(self) -> None:
        """background_strict + no callback → permission denied string returned."""
        backend = _make_backend()
        config = ComputerUseConfig(
            execution_mode=ExecutionMode.background_strict, screenshot_delay=0.0
        )
        session = DesktopSession(backend=backend, config=config, permission_callback=None)
        session._last_snapshot_time = time.time()

        with patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.inspect_backend",
            return_value=_NON_SENSITIVE_FG_INFO,
        ):
            result = await session.desktop_vision_action(
                action="left_click", coordinate=[50, 50]
            )

        assert "permission denied" in result.lower()
        assert "background_strict" in result.lower()
        backend.click.assert_not_called()

    @pytest.mark.asyncio
    async def test_background_strict_callback_grants_proceeds(self) -> None:
        """background_strict + callback grants → action executes normally."""
        backend = _make_backend()
        callback = AsyncMock(
            return_value=ForegroundPermissionResult(
                granted=True, scope=ForegroundPermissionScope.session
            )
        )
        config = ComputerUseConfig(
            execution_mode=ExecutionMode.background_strict, screenshot_delay=0.0
        )
        session = DesktopSession(
            backend=backend, config=config, permission_callback=callback
        )
        session._last_snapshot_time = time.time()

        with patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.inspect_backend",
            return_value=_NON_SENSITIVE_FG_INFO,
        ):
            result = await session.desktop_vision_action(
                action="left_click", coordinate=[50, 50]
            )

        callback.assert_called_once()
        assert "permission denied" not in str(result).lower()
        backend.click.assert_called_once()

    @pytest.mark.asyncio
    async def test_background_strict_callback_denies_blocks(self) -> None:
        """background_strict + callback denies → action blocked."""
        backend = _make_backend()
        callback = AsyncMock(
            return_value=ForegroundPermissionResult(granted=False)
        )
        config = ComputerUseConfig(
            execution_mode=ExecutionMode.background_strict, screenshot_delay=0.0
        )
        session = DesktopSession(
            backend=backend, config=config, permission_callback=callback
        )
        session._last_snapshot_time = time.time()

        with patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.inspect_backend",
            return_value=_NON_SENSITIVE_FG_INFO,
        ):
            result = await session.desktop_vision_action(
                action="left_click", coordinate=[50, 50]
            )

        callback.assert_called_once()
        assert "permission denied" in result.lower()
        backend.click.assert_not_called()

    @pytest.mark.asyncio
    async def test_session_scope_caches_for_subsequent_actions(self) -> None:
        """After session grant, subsequent actions skip callback."""
        backend = _make_backend()
        callback = AsyncMock(
            return_value=ForegroundPermissionResult(
                granted=True, scope=ForegroundPermissionScope.session
            )
        )
        config = ComputerUseConfig(
            execution_mode=ExecutionMode.background_strict, screenshot_delay=0.0
        )
        session = DesktopSession(
            backend=backend, config=config, permission_callback=callback
        )
        session._last_snapshot_time = time.time()

        with patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.inspect_backend",
            return_value=_NON_SENSITIVE_FG_INFO,
        ):
            await session.desktop_vision_action(action="left_click", coordinate=[50, 50])
            session._last_snapshot_time = time.time()
            await session.desktop_vision_action(action="type", text="hello")

        assert callback.call_count == 1

    @pytest.mark.asyncio
    async def test_background_safe_actions_skip_permission(self) -> None:
        """'screenshot' and 'wait' are background-safe — no permission needed."""
        backend = _make_backend()
        callback = AsyncMock()
        config = ComputerUseConfig(
            execution_mode=ExecutionMode.background_strict, screenshot_delay=0.0
        )
        session = DesktopSession(
            backend=backend, config=config, permission_callback=callback
        )

        with patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.inspect_backend",
            return_value=_NON_SENSITIVE_FG_INFO,
        ):
            with patch.object(session, "wait_seconds", new_callable=AsyncMock) as mock_wait:
                mock_wait.return_value = ActionResult(success=True)
                result = await session.desktop_vision_action(action="wait")

        callback.assert_not_called()
        assert "permission denied" not in result.lower() if isinstance(result, str) else True

    @pytest.mark.asyncio
    async def test_best_effort_mode_proceeds_without_callback(self) -> None:
        """background_best_effort + no callback → action proceeds (graceful degradation)."""
        backend = _make_backend()
        config = ComputerUseConfig(
            execution_mode=ExecutionMode.background_best_effort, screenshot_delay=0.0
        )
        session = DesktopSession(backend=backend, config=config, permission_callback=None)
        session._last_snapshot_time = time.time()

        with patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.inspect_backend",
            return_value=_NON_SENSITIVE_FG_INFO,
        ):
            result = await session.desktop_vision_action(
                action="left_click", coordinate=[50, 50]
            )

        assert "permission denied" not in str(result).lower()
        backend.click.assert_called_once()


class TestHealerBBoxClickPermissionIntegration:
    """Integration: try_bbox_click full-path permission checks."""

    @pytest.mark.asyncio
    async def test_bbox_click_blocked_in_strict_mode(self) -> None:
        """Healer fallback blocked when background_strict and no callback."""
        backend = _make_backend()
        config = ComputerUseConfig(execution_mode=ExecutionMode.background_strict)
        session = DesktopSession(backend=backend, config=config, permission_callback=None)
        element = _make_element()

        result = await try_bbox_click(
            session=session, element=element, action="click", text="", modifiers=None
        )

        assert result.success is False
        assert "background_strict" in result.error
        backend.click.assert_not_called()

    @pytest.mark.asyncio
    async def test_bbox_click_proceeds_after_grant(self) -> None:
        """Healer fallback proceeds when callback grants permission."""
        backend = _make_backend()
        callback = AsyncMock(
            return_value=ForegroundPermissionResult(
                granted=True, scope=ForegroundPermissionScope.once
            )
        )
        config = ComputerUseConfig(execution_mode=ExecutionMode.background_strict)
        session = DesktopSession(
            backend=backend, config=config, permission_callback=callback
        )
        element = _make_element(x=50, y=60)

        result = await try_bbox_click(
            session=session, element=element, action="click", text="", modifiers=None
        )

        assert result.success is True
        callback.assert_called_once()
        backend.click.assert_called_once_with(70, 70, clicks=1, modifiers=None)

    @pytest.mark.asyncio
    async def test_bbox_fill_action_proceeds_after_grant(self) -> None:
        """Healer 'fill' action: click + type_text after permission grant."""
        backend = _make_backend()
        callback = AsyncMock(
            return_value=ForegroundPermissionResult(
                granted=True, scope=ForegroundPermissionScope.session
            )
        )
        config = ComputerUseConfig(execution_mode=ExecutionMode.background_strict)
        session = DesktopSession(
            backend=backend, config=config, permission_callback=callback
        )
        element = _make_element(x=0, y=0)

        result = await try_bbox_click(
            session=session, element=element, action="fill", text="hello", modifiers=None
        )

        assert result.success is True
        backend.click.assert_called_once()
        backend.type_text.assert_called_once_with("hello")

    @pytest.mark.asyncio
    async def test_bbox_click_denied_by_callback(self) -> None:
        """Healer fallback blocked when callback explicitly denies."""
        backend = _make_backend()
        callback = AsyncMock(
            return_value=ForegroundPermissionResult(granted=False)
        )
        config = ComputerUseConfig(execution_mode=ExecutionMode.background_strict)
        session = DesktopSession(
            backend=backend, config=config, permission_callback=callback
        )
        element = _make_element()

        result = await try_bbox_click(
            session=session, element=element, action="click", text="", modifiers=None
        )

        assert result.success is False
        assert "denied" in result.error.lower()
        backend.click.assert_not_called()

    @pytest.mark.asyncio
    async def test_bbox_click_foreground_mode_skips_gate(self) -> None:
        """In foreground mode, healer proceeds without any permission check."""
        backend = _make_backend()
        callback = AsyncMock()
        config = ComputerUseConfig(execution_mode=ExecutionMode.foreground)
        session = DesktopSession(
            backend=backend, config=config, permission_callback=callback
        )
        element = _make_element(x=10, y=20)

        result = await try_bbox_click(
            session=session, element=element, action="click", text="", modifiers=None
        )

        assert result.success is True
        callback.assert_not_called()
        backend.click.assert_called_once()


class TestDesktopInteractPermissionIntegration:
    """Integration: desktop_interact → AX fail → try_bbox_click → permission gate."""

    @pytest.mark.asyncio
    async def test_interact_ax_fail_falls_to_bbox_blocked(self) -> None:
        """When AX invoke fails, healer is invoked and permission gate blocks."""
        from myrm_agent_harness.toolkits.computer_use.dref.types import SnapshotMeta

        backend = _make_backend()
        config = ComputerUseConfig(
            execution_mode=ExecutionMode.background_strict, screenshot_delay=0.0
        )
        session = DesktopSession(backend=backend, config=config, permission_callback=None)
        session._last_snapshot_time = time.time()

        element = _make_element(x=100, y=200)
        meta = SnapshotMeta(
            ref_count=1, app_name="Safari", window_title="Page",
            scope="foreground", needs_permission=False,
        )
        session._refs.replace({"de0": element}, meta)

        failed_invoke = ActionResult(success=False, error="AX invoke not available")
        with patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.invoke_element",
            return_value=failed_invoke,
        ):
            result = await session.desktop_interact(ref="e0", action="click")

        assert "background_strict" in result.lower() or "denied" in result.lower()
        backend.click.assert_not_called()

    @pytest.mark.asyncio
    async def test_interact_ax_fail_callback_grants_bbox_executes(self) -> None:
        """When AX fails and callback grants, bbox click proceeds."""
        from myrm_agent_harness.toolkits.computer_use.dref.types import SnapshotMeta

        backend = _make_backend()
        callback = AsyncMock(
            return_value=ForegroundPermissionResult(
                granted=True, scope=ForegroundPermissionScope.session
            )
        )
        config = ComputerUseConfig(
            execution_mode=ExecutionMode.background_strict, screenshot_delay=0.0
        )
        session = DesktopSession(
            backend=backend, config=config, permission_callback=callback
        )
        session._last_snapshot_time = time.time()

        element = _make_element(x=100, y=200)
        meta = SnapshotMeta(
            ref_count=1, app_name="Safari", window_title="Page",
            scope="foreground", needs_permission=False,
        )
        session._refs.replace({"de0": element}, meta)

        failed_invoke = ActionResult(success=False, error="AX invoke not available")
        with patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.invoke_element",
            return_value=failed_invoke,
        ), patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.capture_snapshot",
            return_value=(meta, {"de0": element}),
        ), patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.render_snapshot_tree",
            return_value=("tree text", meta),
        ):
            result = await session.desktop_interact(ref="e0", action="click")

        callback.assert_called_once()
        backend.click.assert_called_once()
        assert "succeeded" in result.lower() or "click" in result.lower()


class TestVisionActionVariantsPermission:
    """Integration: non-click vision actions (type, key, scroll, drag) permission gate."""

    @pytest.mark.asyncio
    async def test_type_action_blocked_in_strict(self) -> None:
        """'type' action is foreground-requiring and gets blocked in strict mode."""
        backend = _make_backend()
        config = ComputerUseConfig(
            execution_mode=ExecutionMode.background_strict, screenshot_delay=0.0
        )
        session = DesktopSession(backend=backend, config=config, permission_callback=None)
        session._last_snapshot_time = time.time()

        with patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.inspect_backend",
            return_value=_NON_SENSITIVE_FG_INFO,
        ):
            result = await session.desktop_vision_action(action="type", text="hello")

        assert "permission denied" in result.lower()

    @pytest.mark.asyncio
    async def test_key_action_blocked_in_strict(self) -> None:
        """'key' action blocked without callback in strict mode."""
        backend = _make_backend()
        config = ComputerUseConfig(
            execution_mode=ExecutionMode.background_strict, screenshot_delay=0.0
        )
        session = DesktopSession(backend=backend, config=config, permission_callback=None)
        session._last_snapshot_time = time.time()

        with patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.inspect_backend",
            return_value=_NON_SENSITIVE_FG_INFO,
        ):
            result = await session.desktop_vision_action(action="key", text="Return")

        assert "permission denied" in result.lower()

    @pytest.mark.asyncio
    async def test_scroll_action_blocked_in_strict(self) -> None:
        """'scroll' action blocked in strict mode."""
        backend = _make_backend()
        config = ComputerUseConfig(
            execution_mode=ExecutionMode.background_strict, screenshot_delay=0.0
        )
        session = DesktopSession(backend=backend, config=config, permission_callback=None)
        session._last_snapshot_time = time.time()

        with patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.inspect_backend",
            return_value=_NON_SENSITIVE_FG_INFO,
        ):
            result = await session.desktop_vision_action(
                action="scroll", coordinate=[100, 100], scroll_direction="down"
            )

        assert "permission denied" in result.lower()

    @pytest.mark.asyncio
    async def test_drag_action_blocked_in_strict(self) -> None:
        """'drag' action blocked in strict mode."""
        backend = _make_backend()
        config = ComputerUseConfig(
            execution_mode=ExecutionMode.background_strict, screenshot_delay=0.0
        )
        session = DesktopSession(backend=backend, config=config, permission_callback=None)
        session._last_snapshot_time = time.time()

        with patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.inspect_backend",
            return_value=_NON_SENSITIVE_FG_INFO,
        ):
            result = await session.desktop_vision_action(
                action="drag",
                start_coordinate=[10, 10],
                coordinate=[200, 200],
            )

        assert "permission denied" in result.lower()

    @pytest.mark.asyncio
    async def test_mouse_move_blocked_in_strict(self) -> None:
        """'mouse_move' action blocked in strict mode."""
        backend = _make_backend()
        config = ComputerUseConfig(
            execution_mode=ExecutionMode.background_strict, screenshot_delay=0.0
        )
        session = DesktopSession(backend=backend, config=config, permission_callback=None)
        session._last_snapshot_time = time.time()

        with patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.inspect_backend",
            return_value=_NON_SENSITIVE_FG_INFO,
        ):
            result = await session.desktop_vision_action(
                action="mouse_move", coordinate=[100, 100]
            )

        assert "permission denied" in result.lower()


class TestAlwaysScopePersistence:
    """Integration: 'always' scope grant persists across different action types."""

    @pytest.mark.asyncio
    async def test_always_grant_persists_across_vision_and_healer(self) -> None:
        """After 'always' grant via vision action, healer also skips callback."""
        backend = _make_backend()
        callback = AsyncMock(
            return_value=ForegroundPermissionResult(
                granted=True, scope=ForegroundPermissionScope.always
            )
        )
        config = ComputerUseConfig(
            execution_mode=ExecutionMode.background_strict, screenshot_delay=0.0
        )
        session = DesktopSession(
            backend=backend, config=config, permission_callback=callback
        )
        session._last_snapshot_time = time.time()

        with patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.inspect_backend",
            return_value=_NON_SENSITIVE_FG_INFO,
        ):
            await session.desktop_vision_action(action="left_click", coordinate=[50, 50])

        assert callback.call_count == 1

        element = _make_element(x=30, y=40)
        result = await try_bbox_click(
            session=session, element=element, action="click", text="", modifiers=None
        )
        assert result.success is True
        assert callback.call_count == 1  # NOT called again

    @pytest.mark.asyncio
    async def test_once_scope_does_not_persist(self) -> None:
        """'once' scope requires callback on every subsequent call."""
        backend = _make_backend()
        callback = AsyncMock(
            return_value=ForegroundPermissionResult(
                granted=True, scope=ForegroundPermissionScope.once
            )
        )
        config = ComputerUseConfig(
            execution_mode=ExecutionMode.background_strict, screenshot_delay=0.0
        )
        session = DesktopSession(
            backend=backend, config=config, permission_callback=callback
        )

        element1 = _make_element(x=10, y=10)
        element2 = _make_element(x=20, y=20)

        await try_bbox_click(
            session=session, element=element1, action="click", text="", modifiers=None
        )
        await try_bbox_click(
            session=session, element=element2, action="click", text="", modifiers=None
        )

        assert callback.call_count == 2


class TestCallbackArgsIntegration:
    """Integration: verify callback receives correct reason/operation from real code paths."""

    @pytest.mark.asyncio
    async def test_vision_action_callback_args(self) -> None:
        """Callback from desktop_vision_action has correct reason and operation."""
        backend = _make_backend()
        callback = AsyncMock(
            return_value=ForegroundPermissionResult(
                granted=True, scope=ForegroundPermissionScope.once
            )
        )
        config = ComputerUseConfig(
            execution_mode=ExecutionMode.background_strict, screenshot_delay=0.0
        )
        session = DesktopSession(
            backend=backend, config=config, permission_callback=callback
        )
        session._last_snapshot_time = time.time()

        with patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.inspect_backend",
            return_value=_NON_SENSITIVE_FG_INFO,
        ):
            await session.desktop_vision_action(action="left_click", coordinate=[50, 50])

        call_kwargs = callback.call_args.kwargs
        assert "left_click" in call_kwargs["reason"]
        assert "desktop_vision_action(left_click)" == call_kwargs["operation"]
        assert call_kwargs["estimated_duration_seconds"] == 5.0

    @pytest.mark.asyncio
    async def test_healer_callback_args(self) -> None:
        """Callback from try_bbox_click has correct reason and operation."""
        backend = _make_backend()
        callback = AsyncMock(
            return_value=ForegroundPermissionResult(
                granted=True, scope=ForegroundPermissionScope.once
            )
        )
        config = ComputerUseConfig(execution_mode=ExecutionMode.background_strict)
        session = DesktopSession(
            backend=backend, config=config, permission_callback=callback
        )
        element = _make_element(x=100, y=200)

        await try_bbox_click(
            session=session, element=element, action="click", text="", modifiers=None
        )

        call_kwargs = callback.call_args.kwargs
        assert "AX invoke failed for @e0" in call_kwargs["reason"]
        assert "bbox_click(120, 210)" == call_kwargs["operation"]
        assert call_kwargs["estimated_duration_seconds"] == 3.0
