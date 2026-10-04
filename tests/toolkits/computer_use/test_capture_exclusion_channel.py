"""Unit tests for the macOS overlay-excluded capture channel.

Pure-mock, headless-safe: Quartz and AppKit are stubbed via ``sys.modules``
injection, so the suite runs on any platform and never touches real screen
capture or window services.

Coverage targets (line + branch complete for the exclusion channel):
- ``_lowest_overlay_window_id``: z-order anchor pick (lowest overlay window),
  no-match, backend failure, malformed/missing window numbers.
- ``_capture_screen_excluding_titles``: anchor-miss fallback, channel failure,
  empty image, PNG serialization success/none/error, AppKit unavailable.
- ``MacOSBackend`` injection routing: excluded-channel route, fallback to the
  legacy ``screencapture -x -C`` path, targeted-window bypass (exclusion never
  applies to directed captures), empty-titles fast path.
"""

from __future__ import annotations

import asyncio
import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.computer_use.backends import macos as macos_mod
from myrm_agent_harness.toolkits.computer_use.backends import macos_background
from myrm_agent_harness.toolkits.computer_use.backends.macos_background import (
    _capture_screen_excluding_titles,
    _lowest_overlay_window_id,
)

_CURTAIN = frozenset({"Privacy Curtain"})


@pytest.fixture()
def quartz_stub(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Inject a Quartz stub; sentinel constants make call-arg assertions exact."""
    stub = MagicMock(name="Quartz")
    stub.kCGNullWindowID = 0
    stub.kCGWindowListOptionOnScreenOnly = 1
    stub.kCGWindowListOptionOnScreenBelowWindow = 2
    stub.kCGWindowImageDefault = 4
    stub.CGRectNull = MagicMock(name="CGRectNull")
    monkeypatch.setitem(sys.modules, "Quartz", stub)
    return stub


class _FakeAppKitRep:
    """Mimic ``NSBitmapImageRep.alloc().initWithCGImage_().representationUsingType_properties_()``."""

    def __init__(
        self,
        payload: bytes | None,
        serialize_error: Exception | None = None,
    ) -> None:
        self._payload = payload
        self._serialize_error = serialize_error
        self.init_images: list[object] = []
        self.serialize_calls: list[tuple[object, object]] = []

    def alloc(self) -> "_FakeAppKitRep":
        return self

    def initWithCGImage_(self, image: object) -> "_FakeAppKitRep":
        self.init_images.append(image)
        return self

    def representationUsingType_properties_(
        self, file_type: object, properties: object
    ) -> bytes | None:
        self.serialize_calls.append((file_type, properties))
        if self._serialize_error is not None:
            raise self._serialize_error
        return self._payload


def _install_appkit(monkeypatch: pytest.MonkeyPatch, rep: _FakeAppKitRep) -> None:
    """Install an AppKit stub exposing the two PNG serialization symbols."""
    module = ModuleType("AppKit")
    setattr(module, "NSBitmapImageFileTypePNG", 4)
    setattr(module, "NSBitmapImageRep", rep)
    monkeypatch.setitem(sys.modules, "AppKit", module)


def _fake_screencapture_proc() -> MagicMock:
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(b"", b""))
    proc.returncode = 0
    return proc


class TestLowestOverlayWindowId:
    """Anchor selection: the z-order LOWEST title match, fail-soft everywhere."""

    def test_returns_lowest_z_order_match(self, quartz_stub: MagicMock) -> None:
        # Window list is ordered front -> back; the anchor must be the LAST
        # matching overlay (first seen when reversed), not the frontmost one.
        quartz_stub.CGWindowListCopyWindowInfo.return_value = [
            {"kCGWindowName": "Privacy Curtain", "kCGWindowNumber": 101},
            {"kCGWindowName": "Desktop", "kCGWindowNumber": 50},
            {"kCGWindowName": "Privacy Curtain", "kCGWindowNumber": 102},
        ]
        assert _lowest_overlay_window_id(_CURTAIN) == 102

    def test_no_title_match_returns_none(self, quartz_stub: MagicMock) -> None:
        # Windows without kCGWindowName default to "" and never match.
        quartz_stub.CGWindowListCopyWindowInfo.return_value = [
            {"kCGWindowNumber": 7},
            {"kCGWindowName": "Desktop", "kCGWindowNumber": 8},
        ]
        assert _lowest_overlay_window_id(_CURTAIN) is None

    def test_backend_error_returns_none(self, quartz_stub: MagicMock) -> None:
        quartz_stub.CGWindowListCopyWindowInfo.side_effect = RuntimeError("denied")
        assert _lowest_overlay_window_id(_CURTAIN) is None

    def test_malformed_window_number_returns_none(self, quartz_stub: MagicMock) -> None:
        # A matched title with an unusable window id degrades (None) rather
        # than guessing a different anchor.
        quartz_stub.CGWindowListCopyWindowInfo.return_value = [
            {"kCGWindowName": "Privacy Curtain", "kCGWindowNumber": "not-a-number"}
        ]
        assert _lowest_overlay_window_id(_CURTAIN) is None
        quartz_stub.CGWindowListCopyWindowInfo.return_value = [
            {"kCGWindowName": "Privacy Curtain", "kCGWindowNumber": None}
        ]
        assert _lowest_overlay_window_id(_CURTAIN) is None

    def test_missing_window_number_key_defaults_to_zero(
        self, quartz_stub: MagicMock
    ) -> None:
        # Absent kCGWindowNumber yields 0; the caller treats falsy anchors as
        # "no anchor" and degrades to the legacy path.
        quartz_stub.CGWindowListCopyWindowInfo.return_value = [
            {"kCGWindowName": "Privacy Curtain"}
        ]
        assert _lowest_overlay_window_id(_CURTAIN) == 0


class TestCaptureScreenExcludingTitles:
    """Channel behavior: degrade to None on every failure, bytes on success."""

    def test_no_anchor_returns_none_without_channel_call(
        self, quartz_stub: MagicMock
    ) -> None:
        for anchor in (None, 0):
            with patch.object(
                macos_background, "_lowest_overlay_window_id", MagicMock(return_value=anchor)
            ):
                assert _capture_screen_excluding_titles(_CURTAIN) is None
        quartz_stub.CGWindowListCreateImage.assert_not_called()

    def test_channel_exception_returns_none(self, quartz_stub: MagicMock) -> None:
        quartz_stub.CGWindowListCreateImage.side_effect = RuntimeError("capture denied")
        with patch.object(
            macos_background, "_lowest_overlay_window_id", MagicMock(return_value=77)
        ):
            assert _capture_screen_excluding_titles(_CURTAIN) is None

    def test_empty_image_returns_none(self, quartz_stub: MagicMock) -> None:
        quartz_stub.CGWindowListCreateImage.return_value = None
        with patch.object(
            macos_background, "_lowest_overlay_window_id", MagicMock(return_value=77)
        ):
            assert _capture_screen_excluding_titles(_CURTAIN) is None

    def test_success_serializes_png_and_passes_channel_args(
        self, quartz_stub: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        image = object()
        quartz_stub.CGWindowListCreateImage.return_value = image
        rep = _FakeAppKitRep(payload=b"\x89PNG-fake")
        _install_appkit(monkeypatch, rep)

        with patch.object(
            macos_background, "_lowest_overlay_window_id", MagicMock(return_value=77)
        ):
            result = _capture_screen_excluding_titles(_CURTAIN)

        assert result == b"\x89PNG-fake"
        args = quartz_stub.CGWindowListCreateImage.call_args[0]
        assert args[0] is quartz_stub.CGRectNull
        assert args[1] is quartz_stub.kCGWindowListOptionOnScreenBelowWindow
        assert args[2] == 77
        assert args[3] is quartz_stub.kCGWindowImageDefault
        assert rep.init_images == [image]
        assert rep.serialize_calls == [(4, None)]

    def test_png_none_returns_none(
        self, quartz_stub: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        quartz_stub.CGWindowListCreateImage.return_value = object()
        _install_appkit(monkeypatch, _FakeAppKitRep(payload=None))
        with patch.object(
            macos_background, "_lowest_overlay_window_id", MagicMock(return_value=77)
        ):
            assert _capture_screen_excluding_titles(_CURTAIN) is None

    def test_appkit_unavailable_returns_none(self, quartz_stub: MagicMock) -> None:
        quartz_stub.CGWindowListCreateImage.return_value = object()
        with (
            patch.dict("sys.modules", {"AppKit": None}),
            patch.object(
                macos_background, "_lowest_overlay_window_id", MagicMock(return_value=77)
            ),
        ):
            assert _capture_screen_excluding_titles(_CURTAIN) is None

    def test_png_serialization_error_returns_none(
        self, quartz_stub: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        quartz_stub.CGWindowListCreateImage.return_value = object()
        _install_appkit(
            monkeypatch,
            _FakeAppKitRep(payload=b"x", serialize_error=RuntimeError("boom")),
        )
        with patch.object(
            macos_background, "_lowest_overlay_window_id", MagicMock(return_value=77)
        ):
            assert _capture_screen_excluding_titles(_CURTAIN) is None


class TestMacOSBackendExclusionRouting:
    """Backend routing: injection activates the channel; fallbacks stay honest."""

    def test_injected_titles_route_to_exclusion_channel(self) -> None:
        backend = macos_mod.MacOSBackend()
        backend.set_excluded_capture_window_titles(["Privacy Curtain"])
        assert backend._excluded_capture_titles == frozenset({"Privacy Curtain"})

        channel = MagicMock(return_value=b"EXCLUDED")
        with patch.object(macos_mod, "_capture_screen_excluding_titles", channel):
            result = asyncio.run(backend.screenshot())

        assert result == b"EXCLUDED"
        channel.assert_called_once_with(frozenset({"Privacy Curtain"}))

    def test_channel_none_falls_back_to_legacy_screencapture(self) -> None:
        backend = macos_mod.MacOSBackend()
        backend.set_excluded_capture_window_titles(["Privacy Curtain"])

        exec_mock = AsyncMock(return_value=_fake_screencapture_proc())
        with (
            patch.object(
                macos_mod, "_capture_screen_excluding_titles", MagicMock(return_value=None)
            ),
            patch("asyncio.create_subprocess_exec", exec_mock),
            patch("pathlib.Path.read_bytes", MagicMock(return_value=b"LEGACY")),
            patch("pathlib.Path.unlink"),
        ):
            result = asyncio.run(backend.screenshot())

        assert result == b"LEGACY"
        args = exec_mock.call_args[0]
        assert args[0] == "screencapture"
        assert "-x" in args
        assert "-C" in args

    def test_targeted_window_bypasses_exclusion_channel(self) -> None:
        backend = macos_mod.MacOSBackend()
        backend.set_excluded_capture_window_titles(["Privacy Curtain"])

        channel = MagicMock(return_value=b"EXCLUDED")
        window_png = AsyncMock(return_value=b"WINDOW")
        target = macos_background._WindowTarget(
            pid=200, window_id=42, bounds=(0, 0, 800, 600)
        )
        with (
            patch.object(
                macos_mod, "_resolve_target_window", MagicMock(return_value=target)
            ),
            patch.object(macos_mod, "_capture_window_png", window_png),
            patch.object(macos_mod, "_capture_screen_excluding_titles", channel),
        ):
            result = asyncio.run(backend.screenshot(app_name="Excel"))

        assert result == b"WINDOW"
        window_png.assert_awaited_once_with(42)
        channel.assert_not_called()

    def test_missing_target_window_raises_and_never_fullscreen(self) -> None:
        backend = macos_mod.MacOSBackend()
        backend.set_excluded_capture_window_titles(["Privacy Curtain"])

        channel = MagicMock(return_value=b"EXCLUDED")
        with (
            patch.object(
                macos_mod, "_resolve_target_window", MagicMock(return_value=None)
            ),
            patch.object(macos_mod, "_capture_screen_excluding_titles", channel),
        ):
            with pytest.raises(RuntimeError, match="no on-screen window"):
                asyncio.run(backend.screenshot(app_name="Ghost"))

        channel.assert_not_called()

    def test_empty_titles_go_straight_to_legacy_path(self) -> None:
        backend = macos_mod.MacOSBackend()
        backend.set_excluded_capture_window_titles([])
        assert backend._excluded_capture_titles == frozenset()

        channel = MagicMock(return_value=b"EXCLUDED")
        exec_mock = AsyncMock(return_value=_fake_screencapture_proc())
        with (
            patch.object(macos_mod, "_capture_screen_excluding_titles", channel),
            patch("asyncio.create_subprocess_exec", exec_mock),
            patch("pathlib.Path.read_bytes", MagicMock(return_value=b"LEGACY")),
            patch("pathlib.Path.unlink"),
        ):
            result = asyncio.run(backend.screenshot())

        assert result == b"LEGACY"
        channel.assert_not_called()

    def test_legacy_screencapture_failure_raises(self) -> None:
        backend = macos_mod.MacOSBackend()
        backend.set_excluded_capture_window_titles(["Privacy Curtain"])

        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"", b"nope"))
        proc.returncode = 1
        with (
            patch.object(
                macos_mod, "_capture_screen_excluding_titles", MagicMock(return_value=None)
            ),
            patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)),
            patch("pathlib.Path.unlink"),
        ):
            with pytest.raises(RuntimeError, match="screencapture failed"):
                asyncio.run(backend.screenshot())