"""Unit tests for ScreenDetector and physical sleep/lock screen gates in ComputerUse."""

from __future__ import annotations

import math
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.computer_use.backends.protocols import ComputerBackend
from myrm_agent_harness.toolkits.computer_use.desktop_session import DesktopSession
from myrm_agent_harness.toolkits.computer_use.safety import (
    PhysicalSleepInterruptionError,
    ScreenLockedInterruptionError,
    check_screen_lock_safety,
    ensure_screen_safe,
)
from myrm_agent_harness.toolkits.computer_use.screen_detector import (
    ScreenDetector,
    hid_idle_seconds,
)
from myrm_agent_harness.toolkits.computer_use.session import ComputerSession
from myrm_agent_harness.toolkits.computer_use.types import (
    ActionResult,
    ScreenContext,
    ScreenInfo,
    ScreenLockState,
)


def _make_mock_backend() -> ComputerBackend:
    backend = MagicMock(spec=ComputerBackend)
    backend.click = AsyncMock(return_value=ActionResult(success=True))
    backend.type_text = AsyncMock(return_value=ActionResult(success=True))
    backend.key = AsyncMock(return_value=ActionResult(success=True))
    backend.mouse_move = AsyncMock(return_value=ActionResult(success=True))
    backend.scroll = AsyncMock(return_value=ActionResult(success=True))
    backend.drag = AsyncMock(return_value=ActionResult(success=True))
    backend.wait = AsyncMock(return_value=ActionResult(success=True))
    backend.screenshot = AsyncMock(return_value=b"\x89PNG\r\n\x1a\nfake")
    backend.screen_info.return_value = ScreenInfo(width=1920, height=1080, dpi_scale=1.0)
    backend.screen_context.return_value = ScreenContext(active_window="Finder", mouse_x=100, mouse_y=100)
    backend.is_screen_locked.return_value = False
    backend.is_display_asleep.return_value = False
    return backend


class TestScreenDetector:
    def test_override_state(self) -> None:
        detector = ScreenDetector(cache_ttl_sec=1.0)
        assert detector.get_state() in (ScreenLockState.UNLOCKED, ScreenLockState.LOCKED, ScreenLockState.UNKNOWN)

        detector.set_override_state(ScreenLockState.LOCKED)
        assert detector.get_state() == ScreenLockState.LOCKED
        assert detector.is_locked() is True

        detector.set_override_state(ScreenLockState.SLEEPING)
        assert detector.get_state() == ScreenLockState.SLEEPING
        assert detector.is_locked() is True

        detector.set_override_state(ScreenLockState.UNLOCKED)
        assert detector.get_state() == ScreenLockState.UNLOCKED
        assert detector.is_locked() is False

    def test_ttl_caching(self) -> None:
        detector = ScreenDetector(cache_ttl_sec=0.5)
        with patch.object(detector, "_probe_native_state", return_value=ScreenLockState.UNLOCKED) as probe:
            # First call probes native
            s1 = detector.get_state()
            assert s1 == ScreenLockState.UNLOCKED
            assert probe.call_count == 1

            # Second call within TTL reuses cache
            s2 = detector.get_state()
            assert s2 == ScreenLockState.UNLOCKED
            assert probe.call_count == 1

            # Force refresh triggers probe
            s3 = detector.get_state(force_refresh=True)
            assert s3 == ScreenLockState.UNLOCKED
            assert probe.call_count == 2

    def test_headless_detection(self) -> None:
        detector = ScreenDetector()
        with patch.dict("os.environ", {"CI": "1"}):
            assert detector.is_headless is True
            assert detector.get_state() == ScreenLockState.UNLOCKED

        with patch.dict("os.environ", {"MYRM_HEADLESS": "1"}, clear=True):
            assert detector.is_headless is True
            assert detector.get_state() == ScreenLockState.UNLOCKED


@pytest.mark.skipif(sys.platform != "darwin", reason="Quartz session dictionary is macOS-only")
class TestMacOSProbe:
    """Quartz session-dictionary mapping; the live probe runs against the real OS."""

    def test_locked_session(self) -> None:
        with patch("Quartz.CGSessionCopyCurrentDictionary", return_value={"CGSSessionScreenIsLocked": 1}):
            assert ScreenDetector()._probe_macos() == ScreenLockState.LOCKED

    def test_display_shutdown_is_sleeping(self) -> None:
        with patch("Quartz.CGSessionCopyCurrentDictionary", return_value={"CGSSessionOnDisplayShutdown": 1}):
            assert ScreenDetector()._probe_macos() == ScreenLockState.SLEEPING

    def test_lock_wins_over_display_shutdown(self) -> None:
        session = {"CGSSessionScreenIsLocked": 1, "CGSSessionOnDisplayShutdown": 1}
        with patch("Quartz.CGSessionCopyCurrentDictionary", return_value=session):
            assert ScreenDetector()._probe_macos() == ScreenLockState.LOCKED

    @pytest.mark.parametrize("session", [{}, {"CGSSessionScreenIsLocked": 0}, None])
    def test_plain_or_missing_session_is_unlocked(self, session: dict[str, int] | None) -> None:
        with patch("Quartz.CGSessionCopyCurrentDictionary", return_value=session):
            assert ScreenDetector()._probe_macos() == ScreenLockState.UNLOCKED

    def test_live_probe_is_fast_and_definite(self) -> None:
        detector = ScreenDetector()
        started = time.perf_counter()
        state = detector._probe_macos()
        elapsed = time.perf_counter() - started
        assert state in (ScreenLockState.UNLOCKED, ScreenLockState.LOCKED, ScreenLockState.SLEEPING)
        # The native call replaces a ~300 ms osascript spawn; stay far below that.
        assert elapsed < 0.1


class TestProbeFailureReporting:
    def test_nil_session_dictionary_reports_unknown(self) -> None:
        detector = ScreenDetector()
        with patch.object(detector, "_probe_macos", return_value=ScreenLockState.UNKNOWN):
            assert detector.get_state(force_refresh=True) == ScreenLockState.UNKNOWN
            assert detector.is_locked() is True

    def test_missing_quartz_reports_unknown_not_unlocked(self) -> None:
        detector = ScreenDetector()
        with patch.object(sys, "platform", "darwin"), patch.dict(sys.modules, {"Quartz": None}):
            assert detector._probe_native_state() == ScreenLockState.UNKNOWN
            assert detector.is_locked() is True


class TestHidIdleSeconds:
    """Human-presence primitive: only a proven idle time may be reported, everything else is None."""

    @pytest.mark.skipif(sys.platform != "darwin", reason="HID idle probe is macOS-only")
    def test_live_probe_reports_a_non_negative_reading(self) -> None:
        idle = hid_idle_seconds()
        assert idle is not None
        assert idle >= 0.0

    @pytest.mark.skipif(sys.platform != "darwin", reason="HID idle probe is macOS-only")
    def test_reads_hardware_state_for_any_input_event(self) -> None:
        """Presence must come from hardware sources: the combined session state also counts synthetic events."""
        import Quartz

        with patch("Quartz.CGEventSourceSecondsSinceLastEventType", return_value=3.5) as probe:
            assert hid_idle_seconds() == 3.5
        probe.assert_called_once_with(Quartz.kCGEventSourceStateHIDSystemState, Quartz.kCGAnyInputEventType)

    @pytest.mark.skipif(sys.platform != "darwin", reason="HID idle probe is macOS-only")
    @pytest.mark.parametrize("reading", [math.nan, math.inf, -1.0])
    def test_unusable_reading_is_unknown(self, reading: float) -> None:
        """NaN would compare below no threshold and look like absence: it must surface as unknown instead."""
        with patch("Quartz.CGEventSourceSecondsSinceLastEventType", return_value=reading):
            assert hid_idle_seconds() is None

    @pytest.mark.skipif(sys.platform != "darwin", reason="HID idle probe is macOS-only")
    def test_probe_error_is_unknown(self) -> None:
        with patch("Quartz.CGEventSourceSecondsSinceLastEventType", side_effect=RuntimeError("probe broke")):
            assert hid_idle_seconds() is None

    def test_missing_quartz_is_unknown_not_idle(self) -> None:
        with patch.object(sys, "platform", "darwin"), patch.dict(sys.modules, {"Quartz": None}):
            assert hid_idle_seconds() is None

    @pytest.mark.parametrize("platform", ["win32", "linux"])
    def test_platforms_without_a_probe_are_unknown(self, platform: str) -> None:
        with patch.object(sys, "platform", platform):
            assert hid_idle_seconds() is None


class TestSafetyGuards:
    def test_check_screen_lock_safety(self) -> None:
        detector = ScreenDetector()
        detector.set_override_state(ScreenLockState.UNLOCKED)
        assert check_screen_lock_safety(detector) is None

        detector.set_override_state(ScreenLockState.LOCKED)
        msg = check_screen_lock_safety(detector)
        assert msg is not None
        assert "Screen is locked" in msg

        detector.set_override_state(ScreenLockState.SLEEPING)
        msg = check_screen_lock_safety(detector)
        assert msg is not None
        assert "Display is sleeping" in msg

    def test_ensure_screen_safe_raises(self) -> None:
        detector = ScreenDetector()
        detector.set_override_state(ScreenLockState.LOCKED)
        with pytest.raises(ScreenLockedInterruptionError):
            ensure_screen_safe(detector)

        detector.set_override_state(ScreenLockState.SLEEPING)
        with pytest.raises(PhysicalSleepInterruptionError):
            ensure_screen_safe(detector)

        detector.set_override_state(ScreenLockState.UNLOCKED)
        ensure_screen_safe(detector)  # Should not raise


@pytest.mark.asyncio
class TestComputerSessionInterruption:
    async def test_actions_blocked_when_locked(self) -> None:
        backend = _make_mock_backend()
        backend.is_screen_locked.return_value = True

        session = ComputerSession(backend=backend)

        with pytest.raises(ScreenLockedInterruptionError):
            await session.click_at(100, 100)
        assert backend.click.call_count == 0

        with pytest.raises(ScreenLockedInterruptionError):
            await session.type_text("secret_password\n")
        assert backend.type_text.call_count == 0

        with pytest.raises(ScreenLockedInterruptionError):
            await session.key_press("Return")
        assert backend.key.call_count == 0

        with pytest.raises(ScreenLockedInterruptionError):
            await session.mouse_move_to(200, 200)
        assert backend.mouse_move.call_count == 0

        with pytest.raises(ScreenLockedInterruptionError):
            await session.scroll_at(200, 200, "down")
        assert backend.scroll.call_count == 0

        with pytest.raises(ScreenLockedInterruptionError):
            await session.drag(10, 10, 50, 50)
        assert backend.drag.call_count == 0

    async def test_actions_blocked_when_sleeping(self) -> None:
        backend = _make_mock_backend()
        backend.is_display_asleep.return_value = True

        session = ComputerSession(backend=backend)

        with pytest.raises(PhysicalSleepInterruptionError):
            await session.click_at(100, 100)
        assert backend.click.call_count == 0

    async def test_reanchor_visual_state(self) -> None:
        backend = _make_mock_backend()
        session = ComputerSession(backend=backend)
        session._last_screenshot_bytes = b"cached"

        session.reanchor_visual_state()
        assert session._last_screenshot_bytes is None
        assert session.scaler is None


@pytest.mark.asyncio
class TestDesktopSessionInterruption:
    async def test_desktop_snapshot_aborted_when_locked(self) -> None:
        backend = _make_mock_backend()
        backend.is_screen_locked.return_value = True

        session = DesktopSession(backend=backend)
        res = await session.desktop_snapshot()
        assert isinstance(res, str)
        assert "Safety: Desktop screen is locked" in res

    async def test_desktop_interact_and_vision_aborted_when_locked(self) -> None:
        backend = _make_mock_backend()
        backend.is_screen_locked.return_value = True

        session = DesktopSession(backend=backend)
        res_interact = await session.desktop_interact("ref1", "click")
        assert "Safety: Screen is locked" in str(res_interact)
        assert backend.click.call_count == 0

        res_vision = await session.desktop_vision_action("left_click", coordinate=[100, 100])
        assert "Safety: Screen is locked" in str(res_vision)
        assert backend.click.call_count == 0


def test_macos_input_write_interrupted_when_locked() -> None:
    from myrm_agent_harness.toolkits.computer_use.backends import macos_input
    from myrm_agent_harness.toolkits.computer_use.screen_detector import get_default_screen_detector

    detector = get_default_screen_detector()
    detector.set_override_state(ScreenLockState.LOCKED)
    try:
        with pytest.raises(ScreenLockedInterruptionError):
            macos_input.write("hello_world")
    finally:
        detector.set_override_state(None)
