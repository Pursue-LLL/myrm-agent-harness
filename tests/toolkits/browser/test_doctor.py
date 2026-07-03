"""Unit tests for browser doctor diagnostics."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.doctor import (
    CheckStatus,
    _check_browser_executable,
    _check_camoufox,
    _check_memory,
    _check_patchright,
    _check_proxy,
    format_report,
    run_doctor,
)


def test_check_patchright_installed() -> None:
    """Test patchright check when installed."""
    mock_patchright = MagicMock()
    mock_patchright.__version__ = "1.50.0"

    with patch.dict("sys.modules", {"patchright": mock_patchright}):
        result = _check_patchright()
        assert result.status == CheckStatus.OK
        assert "1.50.0" in result.message


def test_check_patchright_missing() -> None:
    """Test patchright check when not installed."""
    with patch.dict("sys.modules", {"patchright": None}):
        import importlib

        import myrm_agent_harness.toolkits.browser.doctor as doctor_module

        importlib.reload(doctor_module)

        result = doctor_module._check_patchright()
        assert result.status == CheckStatus.ERROR
        assert result.fix == "uv add patchright"


def test_check_camoufox_installed() -> None:
    """Test camoufox check when installed."""
    mock_camoufox = MagicMock()
    mock_camoufox.__version__ = "0.4.11"

    with patch.dict("sys.modules", {"camoufox": mock_camoufox}):
        result = _check_camoufox()
        assert result.status == CheckStatus.OK
        assert "0.4.11" in result.message


def test_check_camoufox_missing() -> None:
    """Test camoufox check when not installed."""
    with patch.dict("sys.modules", {"camoufox": None}):
        import importlib

        import myrm_agent_harness.toolkits.browser.doctor as doctor_module

        importlib.reload(doctor_module)

        result = doctor_module._check_camoufox()
        assert result.status == CheckStatus.WARNING
        assert "stealth auto-upgrade unavailable" in result.message


def test_format_report_includes_camoufox() -> None:
    """Environment section in CLI report must list camoufox when checked."""
    from myrm_agent_harness.toolkits.browser.doctor import DoctorCheckResult, DoctorReport

    report = DoctorReport(
        checks={
            "camoufox": DoctorCheckResult(
                name="camoufox",
                status=CheckStatus.OK,
                message="camoufox 0.4.11 installed",
            ),
        },
        summary="1/1 checks passed",
        overall_healthy=True,
    )
    rendered = format_report(report)
    assert "camoufox 0.4.11 installed" in rendered


def test_check_browser_executable_default() -> None:
    """Test browser executable check with default bundled browser."""
    with patch.dict(os.environ, {"BROWSER_EXECUTABLE_PATH": ""}, clear=False):
        result = _check_browser_executable()
        assert result.status == CheckStatus.OK
        assert "bundled" in result.message


def test_check_browser_executable_custom_exists(tmp_path: Path) -> None:
    """Test browser executable check with valid custom path."""
    fake_browser = tmp_path / "chromium"
    fake_browser.write_text("#!/bin/sh\necho 'fake browser'")
    fake_browser.chmod(0o755)

    result = _check_browser_executable(str(fake_browser))
    assert result.status == CheckStatus.OK
    assert str(fake_browser) in result.message


def test_check_browser_executable_not_exists() -> None:
    """Test browser executable check with non-existent path."""
    result = _check_browser_executable("/nonexistent/browser")
    assert result.status == CheckStatus.ERROR
    assert "not found" in result.message
    assert result.fix is not None


def test_check_browser_executable_not_executable(tmp_path: Path) -> None:
    """Test browser executable check with non-executable file."""
    fake_browser = tmp_path / "chromium"
    fake_browser.write_text("not executable")
    fake_browser.chmod(0o644)

    result = _check_browser_executable(str(fake_browser))
    assert result.status == CheckStatus.ERROR
    assert "not executable" in result.message
    assert "chmod +x" in result.fix


def test_check_memory_psutil_missing() -> None:
    """Test memory check when psutil not installed."""
    with patch.dict("sys.modules", {"psutil": None}):
        result = _check_memory()
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
        from importlib import reload

        import myrm_agent_harness.toolkits.browser.doctor as doctor_module

        reload(doctor_module)

        result = doctor_module._check_memory()
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
        from importlib import reload

        import myrm_agent_harness.toolkits.browser.doctor as doctor_module

        reload(doctor_module)

        result = doctor_module._check_memory()
        assert result.status == CheckStatus.OK


def test_check_disk_ok() -> None:
    """Test disk check with sufficient space."""
    mock_psutil = MagicMock()
    mock_usage = MagicMock()
    mock_usage.free = 10 * 1024**3
    mock_usage.percent = 50.0
    mock_psutil.disk_usage.return_value = mock_usage

    with patch.dict("sys.modules", {"psutil": mock_psutil}):
        from importlib import reload

        import myrm_agent_harness.toolkits.browser.doctor as doctor_module

        reload(doctor_module)

        result = doctor_module._check_disk()
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


@pytest.mark.asyncio
async def test_run_doctor_skip_launch() -> None:
    """Test run_doctor without launch test."""
    report = await run_doctor(include_launch_test=False, include_orphan_check=False)

    assert "patchright" in report.checks
    assert "browser_executable" in report.checks
    assert "memory" in report.checks
    assert "disk" in report.checks
    assert "proxy" in report.checks
    assert "browser_launch" not in report.checks
    assert "orphan_processes" not in report.checks

    assert isinstance(report.summary, str)
    assert isinstance(report.overall_healthy, bool)


@pytest.mark.asyncio
async def test_run_doctor_with_orphan_check() -> None:
    """Test run_doctor includes orphan check when enabled."""
    report = await run_doctor(include_launch_test=False, include_orphan_check=True)

    assert "orphan_processes" in report.checks
    assert report.checks["orphan_processes"].status in (CheckStatus.OK, CheckStatus.WARNING)


@pytest.mark.asyncio
async def test_run_doctor_with_launch() -> None:
    """Test run_doctor with launch test."""
    report = await run_doctor(include_launch_test=True)

    assert "browser_launch" in report.checks

    if report.checks["browser_launch"].status == CheckStatus.OK:
        assert report.overall_healthy or report.checks["browser_launch"].status == CheckStatus.WARNING


def test_format_report() -> None:
    """Test report formatting."""
    from myrm_agent_harness.toolkits.browser.doctor import DoctorReport

    report = DoctorReport(
        checks={
            "patchright": _check_patchright(),
            "memory": _check_memory(),
        },
        summary="2/2 checks passed",
        overall_healthy=True,
        recommendations=[],
    )

    output = format_report(report)
    assert "Browser Doctor" in output
    assert "Environment" in output
    assert isinstance(output, str)


def test_format_report_with_warnings_and_errors() -> None:
    """Test report formatting with WARNING and ERROR statuses."""
    from myrm_agent_harness.toolkits.browser.doctor import CheckStatus, DoctorCheckResult, DoctorReport

    report = DoctorReport(
        checks={
            "memory": DoctorCheckResult(
                name="Memory",
                status=CheckStatus.WARNING,
                message="Low memory: 0.8 GB available",
                details={"available_gb": 0.8, "used_percent": 92.0},
            ),
            "browser_executable": DoctorCheckResult(
                name="Browser Executable",
                status=CheckStatus.ERROR,
                message="Custom browser executable not found",
                details={"path": "/nonexistent/chrome", "exists": False},
            ),
        },
        summary="0/2 checks passed, 1 warning, 1 error",
        overall_healthy=False,
        recommendations=[
            "Free up system memory",
            "Verify browser executable path",
        ],
    )

    output = format_report(report)
    assert "Browser Doctor" in output
    assert "·" in output
    assert "" in output
    assert "recommendation" in output.lower()
    assert isinstance(output, str)
