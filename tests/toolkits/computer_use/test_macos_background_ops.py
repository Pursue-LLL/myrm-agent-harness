"""Tests for macOS background operations: PID-targeted input, window capture,
foreground guard, post-event permission, EnhancedUI, and origin-aware scaling.

All macOS-only APIs (Quartz, CoreGraphics) are mocked: this suite runs on
Linux CI. Covers:
- macos_input target routing: default HID vs CGEventPostToPid
- guard_foreground: silent on stable focus, FocusChangedError on leak
- _resolve_target_window: match / missing / malformed entries
- MacOSBackend.screenshot: targeted window vs fullscreen vs missing window
- post-event access probe/request incl. unavailable-API None path
- EnhancedUI fail-soft behavior
- CoordinateScaler origin mapping for window captures
- try_bbox_click macOS branch: routes, guards, and always clears target
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.computer_use.backends import macos_input as macos_input_mod
from myrm_agent_harness.toolkits.computer_use.backends.macos_background import (
    _check_post_event_access,
    _request_post_event_access,
    _resolve_target_window,
    _set_enhanced_ui,
    guard_foreground,
)
from myrm_agent_harness.toolkits.computer_use.coordinate_scaler import (
    CoordinateScaler,
)
from myrm_agent_harness.toolkits.computer_use.dref.errors import FocusChangedError
from myrm_agent_harness.toolkits.computer_use.types import PermissionStatus


@pytest.fixture()
def quartz_stub(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Inject a stub Quartz module so macOS imports work on Linux."""
    stub = MagicMock(name="Quartz")
    stub.kCGHIDEventTap = 0
    stub.kCGWindowListOptionOnScreenOnly = 0
    stub.kCGNullWindowID = 0
    monkeypatch.setitem(sys.modules, "Quartz", stub)
    return stub


class TestInputTargetRouting:
    def test_default_global_hid(self, quartz_stub: MagicMock) -> None:
        macos_input_mod.clear_input_target()
        macos_input_mod._post_event(object())
        quartz_stub.CGEventPost.assert_called_once()
        quartz_stub.CGEventPostToPid.assert_not_called()

    def test_target_pid_direct(self, quartz_stub: MagicMock) -> None:
        macos_input_mod.set_input_target(4242)
        try:
            macos_input_mod._post_event(object())
        finally:
            macos_input_mod.clear_input_target()
        quartz_stub.CGEventPostToPid.assert_called_once()
        args = quartz_stub.CGEventPostToPid.call_args[0]
        assert args[0] == 4242
        quartz_stub.CGEventPost.assert_not_called()

    def test_invalid_pid_resets_to_global(self, quartz_stub: MagicMock) -> None:
        macos_input_mod.set_input_target(-5)
        macos_input_mod._post_event(object())
        quartz_stub.CGEventPost.assert_called_once()
        macos_input_mod.clear_input_target()


class TestForegroundGuard:
    def test_stable_focus_passes(self) -> None:
        with (
            patch(
                "myrm_agent_harness.toolkits.computer_use.backends.macos_background._frontmost_pid",
                side_effect=[100, 100],
            ),guard_foreground()
        ):
            pass

    def test_changed_focus_raises(self) -> None:
        with (
            patch(
                "myrm_agent_harness.toolkits.computer_use.backends.macos_background._frontmost_pid",
                side_effect=[100, 200],
            ),
            pytest.raises(FocusChangedError, match="Foreground app changed"),guard_foreground()
        ):
            pass

    def test_unknown_pid_never_raises(self) -> None:
        with (
            patch(
                "myrm_agent_harness.toolkits.computer_use.backends.macos_background._frontmost_pid",
                return_value=None,
            ),guard_foreground()
        ):
            pass


class TestResolveTargetWindow:
    def _windows(self) -> list[dict[str, object]]:
        return [
            {
                "kCGWindowOwnerName": "Finder",
                "kCGWindowOwnerPID": 100,
                "kCGWindowNumber": 10,
                "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 800, "Height": 600},
            },
            {
                "kCGWindowOwnerName": "Microsoft Excel",
                "kCGWindowOwnerPID": 200,
                "kCGWindowNumber": 11,
                "kCGWindowBounds": {"X": 100, "Y": 50, "Width": 900, "Height": 700},
            },
        ]

    def test_match_by_contains(self, quartz_stub: MagicMock) -> None:
        quartz_stub.CGWindowListCopyWindowInfo.return_value = self._windows()
        target = _resolve_target_window("excel")
        assert target is not None
        assert (target.pid, target.window_id) == (200, 11)
        assert target.bounds == (100, 50, 900, 700)

    def test_missing_app_returns_none(self, quartz_stub: MagicMock) -> None:
        quartz_stub.CGWindowListCopyWindowInfo.return_value = self._windows()
        assert _resolve_target_window("NoSuchApp") is None

    def test_index_out_of_range_returns_none(self, quartz_stub: MagicMock) -> None:
        quartz_stub.CGWindowListCopyWindowInfo.return_value = self._windows()
        assert _resolve_target_window("Finder", window_index=5) is None

    def test_backend_error_returns_none(self, quartz_stub: MagicMock) -> None:
        quartz_stub.CGWindowListCopyWindowInfo.side_effect = RuntimeError("denied")
        assert _resolve_target_window("Finder") is None


class TestTargetedScreenshot:
    def test_missing_window_raises_no_silent_fullscreen(
        self, quartz_stub: MagicMock
    ) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import (
            MacOSBackend,
        )

        quartz_stub.CGWindowListCopyWindowInfo.return_value = []
        backend = MacOSBackend()
        with pytest.raises(RuntimeError, match="no on-screen window"):
            import asyncio

            asyncio.get_event_loop().run_until_complete(
                backend.screenshot(app_name="Ghost")
            )

    def test_other_platforms_raise_loudly(self) -> None:
        import asyncio

        from myrm_agent_harness.toolkits.computer_use.backends.linux import (
            LinuxBackend,
        )
        from myrm_agent_harness.toolkits.computer_use.backends.windows import (
            WindowsBackend,
        )

        async def _run() -> None:
            with pytest.raises(RuntimeError, match="not supported"):
                await LinuxBackend().screenshot(app_name="Excel")
            with pytest.raises(RuntimeError, match="not supported"):
                await WindowsBackend().screenshot(app_name="Excel")

        asyncio.get_event_loop().run_until_complete(_run())


class TestPostEventAccess:
    def test_probe_unavailable_api_returns_none(self) -> None:
        with patch("ctypes.util.find_library", return_value=None):
            assert _check_post_event_access() is None

    def test_probe_grant_values(self) -> None:
        fake_cg = MagicMock()
        with (
            patch("ctypes.util.find_library", return_value="CoreGraphics"),
            patch("ctypes.cdll.LoadLibrary", return_value=fake_cg),
        ):
            fake_cg.CGPreflightPostEventAccess.return_value = True
            assert _check_post_event_access() is True
            fake_cg.CGPreflightPostEventAccess.return_value = False
            assert _check_post_event_access() is False

    def test_request_without_library_is_false(self) -> None:
        with patch("ctypes.util.find_library", return_value=None):
            assert _request_post_event_access() is False

    def test_permission_status_field_defaults_none(self) -> None:
        assert PermissionStatus().post_event_access is None

    def test_all_granted_unchanged_by_new_field(self) -> None:
        # Post-event denial must not flip the existing readiness gates.
        status = PermissionStatus(
            accessibility=True, screen_recording=True, post_event_access=False
        )
        assert status.all_granted is True


class TestEnhancedUI:
    def test_fail_soft_without_library(self) -> None:
        with patch("ctypes.util.find_library", return_value=None):
            assert _set_enhanced_ui(1234) is False

    def test_denied_write_is_contained_and_reprobed(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends import macos_background

        macos_background._enhanced_ui_usable = None
        crashed = MagicMock(returncode=-5, stdout=b"", stderr=b"")
        granted = MagicMock(returncode=0, stdout=b"", stderr=b"")
        with (
            patch("ctypes.util.find_library", return_value="lib"),
            patch("subprocess.run", side_effect=[crashed, granted]) as run,
        ):
            # Denial is contained (parent survives) and NOT cached, so a
            # later grant takes effect without a restart.
            assert _set_enhanced_ui(9999) is False
            assert _set_enhanced_ui(9999) is True
            # Success is cached: no third subprocess.
            assert _set_enhanced_ui(9999) is True
            assert run.call_count == 2
        macos_background._enhanced_ui_usable = None

    def test_rejects_bad_pid(self) -> None:
        assert _set_enhanced_ui(0) is False
        assert _set_enhanced_ui(-1) is False


class TestOriginAwareScaling:
    def test_window_origin_mapping(self) -> None:
        scaler = CoordinateScaler(
            screen_width=900,
            screen_height=700,
            sent_width=450,
            sent_height=350,
            origin_x=100,
            origin_y=50,
        )
        assert scaler.api_to_screen(0, 0) == (100, 50)
        assert scaler.api_to_screen(450, 350) == (1000, 750)
        assert scaler.screen_to_api(100, 50) == (0, 0)

    def test_fullscreen_origin_defaults_zero(self) -> None:
        scaler = CoordinateScaler(
            screen_width=1440, screen_height=900, sent_width=720, sent_height=450
        )
        assert scaler.api_to_screen(0, 0) == (0, 0)


class TestHealerBackgroundRouting:
    def _element(self) -> MagicMock:
        element = MagicMock()
        element.ref_id = "d3"
        element.name = "Save"
        element.bbox.center_x = 10
        element.bbox.center_y = 20
        return element

    def _session(self, pid: int) -> MagicMock:
        from myrm_agent_harness.toolkits.computer_use.dref.types import SnapshotMeta

        session = MagicMock()
        session._refs.meta = SnapshotMeta(
            ref_count=1,
            app_name="Excel",
            window_title="Book",
            scope="target",
            app_id="",
            pid=pid,
        )
        session.check_foreground_permission = AsyncMock(return_value=None)
        return session

    def test_mac_backend_routes_and_clears(self) -> None:
        import asyncio

        from myrm_agent_harness.toolkits.computer_use.backends.macos import (
            MacOSBackend,
        )
        from myrm_agent_harness.toolkits.computer_use.execution.healer import (
            try_bbox_click,
        )

        backend = MacOSBackend()
        backend.click = AsyncMock(
            return_value=MagicMock(success=True, error=None)
        )
        session = self._session(pid=200)
        session._backend = backend
        with (
            patch(
                "myrm_agent_harness.toolkits.computer_use.backends.macos_background._frontmost_pid",
                side_effect=[200, 200],
            ),
        ):
            result = asyncio.get_event_loop().run_until_complete(
                try_bbox_click(session, self._element(), "click", "", None)
            )
        assert result.success is True
        assert macos_input_mod._input_target_pid is None

    def test_focus_leak_reports_failure(self) -> None:
        import asyncio

        from myrm_agent_harness.toolkits.computer_use.backends.macos import (
            MacOSBackend,
        )
        from myrm_agent_harness.toolkits.computer_use.execution.healer import (
            try_bbox_click,
        )

        backend = MacOSBackend()
        backend.click = AsyncMock(
            return_value=MagicMock(success=True, error=None)
        )
        session = self._session(pid=200)
        session._backend = backend
        with (
            patch(
                "myrm_agent_harness.toolkits.computer_use.backends.macos_background._frontmost_pid",
                side_effect=[100, 999],
            ),
        ):
            result = asyncio.get_event_loop().run_until_complete(
                try_bbox_click(session, self._element(), "click", "", None)
            )
        assert result.success is False
        assert "Foreground app changed" in (result.error or "")
        assert macos_input_mod._input_target_pid is None

    def test_pid_less_snapshot_keeps_legacy_path(self) -> None:
        import asyncio

        from myrm_agent_harness.toolkits.computer_use.backends.macos import (
            MacOSBackend,
        )
        from myrm_agent_harness.toolkits.computer_use.execution.healer import (
            try_bbox_click,
        )

        backend = MacOSBackend()
        backend.click = AsyncMock(
            return_value=MagicMock(success=True, error=None)
        )
        session = self._session(pid=0)
        session._backend = backend
        with patch.object(
            macos_input_mod, "set_input_target", wraps=macos_input_mod.set_input_target
        ) as spy:
            result = asyncio.get_event_loop().run_until_complete(
                try_bbox_click(session, self._element(), "click", "", None)
            )
        assert result.success is True
        spy.assert_not_called()
