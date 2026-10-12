"""Tests for the non-downloading Camoufox readiness probe and its launcher gate."""

from __future__ import annotations

import logging
import os
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("camoufox")

from camoufox.exceptions import CamoufoxNotInstalled, UnsupportedVersion

from myrm_agent_harness.toolkits.browser.exceptions import BrowserLaunchError, EngineUnavailableError
from myrm_agent_harness.toolkits.browser.pool.browser_launcher import BrowserLauncher
from myrm_agent_harness.toolkits.browser.pool.camoufox_availability import (
    CAMOUFOX_INSTALL_FIX,
    camoufox_unavailable_reason,
    require_camoufox_ready,
)
from myrm_agent_harness.toolkits.browser.pool.config import BrowserEngine, LaunchMode

_PKGMAN = "camoufox.pkgman"


class _UnloadableModule(types.ModuleType):
    """A camoufox module whose bundled data file cannot be read when it is imported."""

    def __getattr__(self, name: str) -> object:
        raise FileNotFoundError(2, "No such file or directory", "/bundle/camoufox/warnings.yml")


@pytest.fixture(autouse=True)
def _no_executable_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CAMOUFOX_EXECUTABLE_PATH", raising=False)


class TestCamoufoxUnavailableReason:
    def test_ready_when_installed_build_resolves(self, tmp_path: Path) -> None:
        resolve = MagicMock(return_value=tmp_path)
        verify = MagicMock(return_value=str(tmp_path / "camoufox"))
        with patch(f"{_PKGMAN}.camoufox_path", resolve), patch(f"{_PKGMAN}.launch_path", verify):
            assert camoufox_unavailable_reason() is None
        verify.assert_called_once_with(tmp_path)

    def test_probe_never_requests_download(self, tmp_path: Path) -> None:
        resolve = MagicMock(return_value=tmp_path)
        with patch(f"{_PKGMAN}.camoufox_path", resolve), patch(f"{_PKGMAN}.launch_path", MagicMock()):
            camoufox_unavailable_reason()
        resolve.assert_called_once_with(download_if_missing=False)

    def test_not_installed_reason_hides_library_paths(self) -> None:
        raised = CamoufoxNotInstalled("Camoufox is not installed at /home/secret/.cache. Run `camoufox fetch`")
        with patch(f"{_PKGMAN}.camoufox_path", side_effect=raised):
            reason = camoufox_unavailable_reason()
        assert reason == "Camoufox browser build is not installed"

    def test_partial_install_without_executable_is_not_ready(self, tmp_path: Path) -> None:
        with (
            patch(f"{_PKGMAN}.camoufox_path", return_value=tmp_path),
            patch(f"{_PKGMAN}.launch_path", side_effect=CamoufoxNotInstalled("missing exec")),
        ):
            assert camoufox_unavailable_reason() == "Camoufox browser build is not installed"

    def test_unsupported_build_is_not_ready(self) -> None:
        with patch(f"{_PKGMAN}.camoufox_path", side_effect=UnsupportedVersion("too old")):
            reason = camoufox_unavailable_reason()
        assert reason is not None
        assert "incompatible" in reason

    def test_unexpected_probe_failure_is_reported_not_raised(self) -> None:
        with patch(f"{_PKGMAN}.camoufox_path", side_effect=OSError("disk gone")):
            reason = camoufox_unavailable_reason()
        assert reason is not None
        assert "OSError" in reason
        assert "disk gone" not in reason

    def test_executable_override_pointing_to_file_is_ready_without_probing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        binary = tmp_path / "camoufox-bin"
        binary.write_text("#!/bin/sh\n")
        monkeypatch.setenv("CAMOUFOX_EXECUTABLE_PATH", str(binary))
        resolve = MagicMock(side_effect=AssertionError("override must bypass the installed-build probe"))
        with patch(f"{_PKGMAN}.camoufox_path", resolve):
            assert camoufox_unavailable_reason() is None

    def test_executable_override_pointing_nowhere_is_not_ready(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        missing = tmp_path / "ghost"
        monkeypatch.setenv("CAMOUFOX_EXECUTABLE_PATH", str(missing))
        reason = camoufox_unavailable_reason()
        assert reason is not None
        assert "CAMOUFOX_EXECUTABLE_PATH" in reason
        assert str(missing) not in reason

    def test_executable_override_in_untraversable_directory_is_not_ready_instead_of_raising(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The probe feeds Doctor and tool errors, so an unreadable override must never escape as an exception."""
        unreachable = tmp_path / "locked" / "camoufox-bin"
        monkeypatch.setenv("CAMOUFOX_EXECUTABLE_PATH", str(unreachable))
        real_stat = os.stat

        def deny_stat(path: str | os.PathLike[str], *, follow_symlinks: bool = True) -> os.stat_result:
            if str(path) == str(unreachable):
                raise PermissionError(13, "Permission denied", str(path))
            return real_stat(path, follow_symlinks=follow_symlinks)

        monkeypatch.setattr(os, "stat", deny_stat)
        reason = camoufox_unavailable_reason()
        assert reason is not None
        assert "CAMOUFOX_EXECUTABLE_PATH" in reason
        assert str(unreachable) not in reason

    def test_missing_python_package_is_not_ready(self) -> None:
        with patch.dict(sys.modules, {"camoufox": None, "camoufox.exceptions": None, "camoufox.pkgman": None}):
            assert camoufox_unavailable_reason() == "camoufox package is not installed"

    def test_package_that_fails_to_load_is_not_ready_instead_of_raising(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Importing camoufox reads bundled data files, so a damaged or partial install fails with OSError, not ImportError."""
        monkeypatch.setitem(sys.modules, "camoufox.pkgman", _UnloadableModule("camoufox.pkgman"))
        reason = camoufox_unavailable_reason()
        assert reason == "camoufox package could not be loaded (FileNotFoundError)"
        assert "/bundle" not in reason


class TestRequireCamoufoxReady:
    def test_noop_when_ready(self) -> None:
        with patch(
            "myrm_agent_harness.toolkits.browser.pool.camoufox_availability.camoufox_unavailable_reason",
            return_value=None,
        ):
            require_camoufox_ready()

    def test_raises_engine_unavailable_with_reason(self) -> None:
        with (
            patch(
                "myrm_agent_harness.toolkits.browser.pool.camoufox_availability.camoufox_unavailable_reason",
                return_value="Camoufox browser build is not installed",
            ),
            pytest.raises(EngineUnavailableError, match="not installed") as exc_info,
        ):
            require_camoufox_ready()
        assert isinstance(exc_info.value, BrowserLaunchError)

    def test_install_fix_covers_missing_package_and_missing_build(self) -> None:
        """Name the package itself: an extra may not carry it, and the ``camoufox`` command needs it."""
        assert "uv add camoufox" in CAMOUFOX_INSTALL_FIX
        assert CAMOUFOX_INSTALL_FIX.index("uv add camoufox") < CAMOUFOX_INSTALL_FIX.index("camoufox fetch")
        assert "CAMOUFOX_EXECUTABLE_PATH" in CAMOUFOX_INSTALL_FIX

    def test_warning_log_for_missing_package_tells_how_to_install_it(self, caplog: pytest.LogCaptureFixture) -> None:
        with (
            patch(
                "myrm_agent_harness.toolkits.browser.pool.camoufox_availability.camoufox_unavailable_reason",
                return_value="camoufox package is not installed",
            ),
            caplog.at_level(logging.WARNING),
            pytest.raises(EngineUnavailableError),
        ):
            require_camoufox_ready()
        assert "uv add camoufox" in caplog.text


class TestLauncherCamoufoxFailure:
    @pytest.mark.asyncio
    async def test_launch_failure_after_ready_never_suggests_chromium_install(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A ready-but-broken Camoufox must not be reported with Chromium install guidance."""
        fake_async_api = types.ModuleType("camoufox.async_api")
        fake_async_api.AsyncCamoufox = MagicMock()  # type: ignore[attr-defined]
        fake_utils = types.ModuleType("camoufox.utils")
        fake_utils.launch_options = MagicMock(  # type: ignore[attr-defined]
            side_effect=Exception("Executable doesn't exist at /x/camoufox")
        )
        monkeypatch.setitem(sys.modules, "camoufox.async_api", fake_async_api)
        monkeypatch.setitem(sys.modules, "camoufox.utils", fake_utils)

        launcher = BrowserLauncher(
            launch_options={"headless": True},
            launch_mode=LaunchMode.LAUNCH,
            engine=BrowserEngine.FIREFOX_CAMOUFOX,
        )

        with (
            patch(
                "myrm_agent_harness.toolkits.browser.pool.camoufox_availability.camoufox_unavailable_reason",
                return_value=None,
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(BrowserLaunchError) as exc_info,
        ):
            await launcher._launch_new_browser()

        message = str(exc_info.value)
        assert "Camoufox stealth engine failed to launch after 3 attempts" in message
        assert "patchright install" not in message
        assert not isinstance(exc_info.value, EngineUnavailableError)
