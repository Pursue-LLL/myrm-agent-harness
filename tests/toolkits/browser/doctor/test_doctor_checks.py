"""Unit tests for the browser doctor environment checks (engines, host resources, proxy)."""

import importlib.metadata
import os
import types
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.doctor import CheckStatus, check_disk, check_memory
from myrm_agent_harness.toolkits.browser.doctor.checks import _check_camoufox, _check_patchright, _check_proxy


def _versionless_module(name: str) -> types.ModuleType:
    """A module shaped like the real patchright package, which exposes no ``__version__``."""
    return types.ModuleType(name)


# A damaged install (interrupted uninstall, corrupt dist-info) must still produce a report: the
# metadata lookup either returns None or raises, and the doctor exists to diagnose such machines.
_UNUSABLE_DISTRIBUTION_METADATA = pytest.mark.parametrize(
    "metadata_lookup",
    [
        pytest.param(MagicMock(side_effect=importlib.metadata.PackageNotFoundError("dist")), id="no-distribution"),
        pytest.param(MagicMock(return_value=None), id="metadata-without-version"),
        pytest.param(
            MagicMock(side_effect=UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")), id="undecodable"
        ),
    ],
)


_CAMOUFOX_REASON_PROBE = "myrm_agent_harness.toolkits.browser.pool.camoufox_availability.camoufox_unavailable_reason"


def test_check_patchright_reports_distribution_metadata_version() -> None:
    """The version must come from distribution metadata because the package has no __version__."""
    with (
        patch.dict("sys.modules", {"patchright": _versionless_module("patchright")}),
        patch("importlib.metadata.version", return_value="1.50.0") as dist_version,
    ):
        result = _check_patchright()
    dist_version.assert_called_once_with("patchright")
    assert result.status == CheckStatus.OK
    assert result.message == "patchright 1.50.0 installed"
    assert result.details == {"version": "1.50.0"}


@_UNUSABLE_DISTRIBUTION_METADATA
def test_check_patchright_reports_unknown_when_distribution_metadata_is_unusable(
    metadata_lookup: MagicMock,
) -> None:
    """An importable package whose metadata is unusable is still reported as installed."""
    with (
        patch.dict("sys.modules", {"patchright": _versionless_module("patchright")}),
        patch("importlib.metadata.version", metadata_lookup),
    ):
        result = _check_patchright()
    assert result.status == CheckStatus.OK
    assert result.message == "patchright unknown installed"
    assert result.details == {"version": "unknown"}


def test_check_patchright_matches_installed_distribution_version() -> None:
    """Anchor against the real package so a stand-in module cannot hide a wrong version source."""
    pytest.importorskip("patchright")
    try:
        expected = importlib.metadata.version("patchright")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("patchright distribution metadata is unavailable")
    assert _check_patchright().details == {"version": expected}


def test_check_patchright_missing() -> None:
    """Test patchright check when not installed."""
    with patch.dict("sys.modules", {"patchright": None}):
        result = _check_patchright()
        assert result.status == CheckStatus.ERROR
        assert result.fix == "uv add patchright"


def test_check_camoufox_ready_reports_installed_package_version() -> None:
    """Version comes from package metadata, not from the camoufox.__version__ submodule object."""
    pytest.importorskip("camoufox")
    with patch(_CAMOUFOX_REASON_PROBE, return_value=None):
        result = _check_camoufox()
    version = importlib.metadata.version("camoufox")
    assert result.status == CheckStatus.OK
    assert result.message == f"camoufox {version} installed"
    assert result.details == {"version": version}


@_UNUSABLE_DISTRIBUTION_METADATA
def test_check_camoufox_reports_unknown_when_distribution_metadata_is_unusable(
    metadata_lookup: MagicMock,
) -> None:
    """A ready browser build is reported as installed even when the package metadata cannot be read."""
    with (
        patch(_CAMOUFOX_REASON_PROBE, return_value=None),
        patch("importlib.metadata.version", metadata_lookup),
    ):
        result = _check_camoufox()
    assert result.status == CheckStatus.OK
    assert result.message == "camoufox unknown installed"
    assert result.details == {"version": "unknown"}


def test_check_camoufox_warns_when_browser_build_missing() -> None:
    """An importable package without its browser build must not be reported as OK."""
    with patch(_CAMOUFOX_REASON_PROBE, return_value="Camoufox browser build is not installed"):
        result = _check_camoufox()
    assert result.status == CheckStatus.WARNING
    assert "browser build is not installed" in result.message
    assert "stealth auto-upgrade unavailable" in result.message
    assert result.fix is not None
    assert "camoufox fetch" in result.fix
    assert "CAMOUFOX_EXECUTABLE_PATH" in result.fix
    assert result.details == {"optional": True}


def test_check_camoufox_warns_when_package_missing() -> None:
    with patch.dict("sys.modules", {"camoufox": None, "camoufox.exceptions": None, "camoufox.pkgman": None}):
        result = _check_camoufox()
    assert result.status == CheckStatus.WARNING
    assert "camoufox package is not installed" in result.message
    assert result.fix is not None
    assert "uv add camoufox" in result.fix
    assert result.details == {"optional": True}


def test_check_memory_psutil_missing() -> None:
    """Test memory check when psutil not installed."""
    with patch.dict("sys.modules", {"psutil": None}):
        result = check_memory()
        assert result.status == CheckStatus.WARNING
        assert "psutil not installed" in result.message


def test_check_memory_low() -> None:
    """Test memory check with low available memory."""
    mock_psutil = MagicMock()
    mock_memory = MagicMock()
    mock_memory.available = 500 * 1024 * 1024
    mock_memory.total = 8 * 1024**3
    mock_memory.percent = 95.0
    mock_psutil.virtual_memory.return_value = mock_memory

    with patch.dict("sys.modules", {"psutil": mock_psutil}):
        result = check_memory()
        assert result.status == CheckStatus.ERROR
        assert "Low memory" in result.message


def test_check_memory_ok() -> None:
    """Test memory check with sufficient memory."""
    mock_psutil = MagicMock()
    mock_memory = MagicMock()
    mock_memory.available = 4 * 1024**3
    mock_memory.total = 16 * 1024**3
    mock_memory.percent = 75.0
    mock_psutil.virtual_memory.return_value = mock_memory

    with patch.dict("sys.modules", {"psutil": mock_psutil}):
        result = check_memory()
        assert result.status == CheckStatus.OK


def test_check_memory_psutil_raises() -> None:
    """Test memory check degrades to WARNING when psutil raises."""
    with patch(
        "psutil.virtual_memory",
        side_effect=OSError("Cannot read /proc/meminfo"),
    ):
        result = check_memory()
    assert result.status == CheckStatus.WARNING
    assert "Cannot check memory" in result.message


def test_check_disk_ok() -> None:
    """Test disk check with sufficient space."""
    mock_psutil = MagicMock()
    mock_usage = MagicMock()
    mock_usage.free = 10 * 1024**3
    mock_usage.percent = 50.0
    mock_psutil.disk_usage.return_value = mock_usage

    with patch.dict("sys.modules", {"psutil": mock_psutil}):
        result = check_disk()
        assert result.status == CheckStatus.OK


def test_check_proxy_not_configured() -> None:
    """Test proxy check when no proxy is set."""
    with patch.dict(os.environ, {"BROWSER_PROXY": ""}, clear=False):
        result = _check_proxy()
        assert result.status == CheckStatus.OK
        assert "No proxy" in result.message


def test_check_proxy_configured() -> None:
    """Test proxy check when proxy is set."""
    result = _check_proxy("http://proxy.example.com:8080")
    assert result.status == CheckStatus.OK
    assert "proxy.example.com" in result.message


def test_check_memory_tight_warning() -> None:
    """Memory check warns when available memory is between 1 and 2 GB."""
    mock_psutil = MagicMock()
    mock_memory = MagicMock()
    mock_memory.available = int(1.5 * 1024**3)
    mock_memory.total = 8 * 1024**3
    mock_memory.percent = 82.0
    mock_psutil.virtual_memory.return_value = mock_memory

    with patch.dict("sys.modules", {"psutil": mock_psutil}):
        result = check_memory()

    assert result.status == CheckStatus.WARNING
    assert "Memory tight" in result.message


def test_check_disk_psutil_missing() -> None:
    """Disk check warns when psutil is unavailable."""

    with patch.dict("sys.modules", {"psutil": None}):
        result = check_disk()

    assert result.status == CheckStatus.WARNING
    assert "psutil not installed" in result.message


def test_check_disk_low_error() -> None:
    """Disk check errors when free space drops below 0.5 GB."""
    mock_psutil = MagicMock()
    mock_usage = MagicMock()
    mock_usage.free = int(0.2 * 1024**3)
    mock_usage.percent = 98.0
    mock_psutil.disk_usage.return_value = mock_usage

    with patch.dict("sys.modules", {"psutil": mock_psutil}):
        result = check_disk()

    assert result.status == CheckStatus.ERROR
    assert "Low disk space" in result.message


def test_check_disk_tight_warning() -> None:
    """Disk check warns when free space is between 0.5 and 1 GB."""
    mock_psutil = MagicMock()
    mock_usage = MagicMock()
    mock_usage.free = int(0.7 * 1024**3)
    mock_usage.percent = 90.0
    mock_psutil.disk_usage.return_value = mock_usage

    with patch.dict("sys.modules", {"psutil": mock_psutil}):
        result = check_disk()

    assert result.status == CheckStatus.WARNING
    assert "Disk space tight" in result.message


def test_check_disk_scan_exception() -> None:
    """Disk check warns with the exception detail when the scan fails."""
    mock_psutil = MagicMock()
    mock_psutil.disk_usage.side_effect = OSError("no such mount")

    with patch.dict("sys.modules", {"psutil": mock_psutil}):
        result = check_disk()

    assert result.status == CheckStatus.WARNING
    assert "Cannot check disk space" in result.message


def test_check_disk_probes_the_runtime_temp_directory() -> None:
    """The probe must measure the volume the browser really writes to, not a hard-coded Unix path."""
    mock_psutil = MagicMock()
    mock_psutil.disk_usage.return_value = MagicMock(free=10 * 1024**3, percent=50.0)

    with (
        patch.dict("sys.modules", {"psutil": mock_psutil}),
        patch("tempfile.gettempdir", return_value="/runtime/tmp"),
    ):
        result = check_disk()

    mock_psutil.disk_usage.assert_called_once_with("/runtime/tmp")
    assert result.status == CheckStatus.OK
