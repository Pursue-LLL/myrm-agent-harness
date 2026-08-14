"""Unit tests for browser doctor diagnostics."""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.doctor import (
    CheckStatus,
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
        assert result.fix is not None
        assert "camoufox>=0.4.11" in result.fix


def test_check_camoufox_missing_fix_string() -> None:
    """Install hint must match production dependency (no invalid [async] extra)."""
    with patch.dict("sys.modules", {"camoufox": None}):
        import importlib

        import myrm_agent_harness.toolkits.browser.doctor as doctor_module

        importlib.reload(doctor_module)

        result = doctor_module._check_camoufox()
        assert "camoufox[async]" not in (result.fix or "")


def test_format_report_includes_camoufox() -> None:
    """Environment section in CLI report must list camoufox when checked."""
    from myrm_agent_harness.toolkits.browser.doctor import (
        DoctorCheckResult,
        DoctorReport,
    )

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


def test_format_report_includes_extension_relay() -> None:
    """Extension Relay section in CLI report must render when checked."""
    from myrm_agent_harness.toolkits.browser.doctor import (
        DoctorCheckResult,
        DoctorReport,
    )

    report = DoctorReport(
        checks={
            "extension_relay": DoctorCheckResult(
                name="extension_relay",
                status=CheckStatus.WARNING,
                message="Server unreachable; cannot verify browser extension CDP relay",
                fix="Start myrm-agent-server and connect the browser extension from WebUI",
            ),
        },
        summary="0/1 checks passed",
        overall_healthy=False,
    )
    rendered = format_report(report)
    assert "Extension Relay" in rendered
    assert "cannot verify browser extension CDP relay" in rendered
    assert "Start myrm-agent-server" in rendered


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


def test_check_memory_psutil_raises() -> None:
    """Test memory check degrades to WARNING when psutil raises."""
    with patch(
        "psutil.virtual_memory",
        side_effect=OSError("Cannot read /proc/meminfo"),
    ):
        result = _check_memory()
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
    assert report.checks["orphan_processes"].status in (
        CheckStatus.OK,
        CheckStatus.WARNING,
    )


@pytest.mark.asyncio
async def test_run_doctor_with_launch() -> None:
    """Test run_doctor with launch test."""
    report = await run_doctor(include_launch_test=True)

    assert "browser_launch" in report.checks

    if report.checks["browser_launch"].status == CheckStatus.OK:
        assert report.overall_healthy or report.checks["browser_launch"].status == CheckStatus.WARNING


@pytest.mark.asyncio
async def test_run_doctor_runs_relay_and_launch_concurrently() -> None:
    """Relay, orphan and launch checks must run concurrently and preserve order."""
    from myrm_agent_harness.toolkits.browser.doctor import (
        DoctorCheckResult,
    )

    relay = DoctorCheckResult(
        name="extension_relay",
        status=CheckStatus.WARNING,
        message="relay mock",
    )
    orphan = DoctorCheckResult(
        name="orphan_processes",
        status=CheckStatus.OK,
        message="orphan mock",
    )
    launch = DoctorCheckResult(
        name="browser_launch",
        status=CheckStatus.OK,
        message="launch mock",
    )

    started: list[str] = []
    relay_completed = asyncio.Event()

    async def fake_relay(_base_url: str = "") -> DoctorCheckResult:
        started.append("relay")
        await relay_completed.wait()
        return relay

    def fake_orphan() -> DoctorCheckResult:
        started.append("orphan")
        return orphan

    async def fake_launch(
        _launch_options: dict[str, object] | None,
    ) -> DoctorCheckResult:
        started.append("launch")
        await asyncio.sleep(0)
        relay_completed.set()
        return launch

    with (
        patch(
            "myrm_agent_harness.toolkits.browser.doctor.checks._check_extension_relay",
            side_effect=fake_relay,
        ),
        patch(
            "myrm_agent_harness.toolkits.browser.doctor.checks.check_orphan_processes",
            side_effect=fake_orphan,
        ),
        patch(
            "myrm_agent_harness.toolkits.browser.doctor.checks._check_browser_launch",
            side_effect=fake_launch,
        ),
    ):
        report = await run_doctor(include_launch_test=True, include_orphan_check=True)

    # relay 阻塞等待时 launch 已启动（否则测试会死锁）；orphan 亦在并发批次中执行
    assert "relay" in started
    assert "launch" in started
    assert "orphan" in started
    assert report.checks["extension_relay"] is relay
    assert report.checks["browser_launch"] is launch
    assert report.checks["orphan_processes"] is orphan


@pytest.mark.asyncio
async def test_check_browser_launch_timeout_graceful() -> None:
    """A hung launch probe must degrade to a graceful ERROR within the timeout."""
    from myrm_agent_harness.toolkits.browser.doctor import DoctorCheckResult
    from myrm_agent_harness.toolkits.browser.doctor.checks import (
        _check_browser_launch,
    )

    async def never_finishes(
        _launch_opts: dict[str, object],
        _async_playwright: object,
    ) -> DoctorCheckResult:
        await asyncio.sleep(60)
        raise AssertionError("probe should have been cancelled by the timeout")

    with (
        patch(
            "myrm_agent_harness.toolkits.browser.doctor.checks._LAUNCH_TIMEOUT_S",
            0.05,
        ),
        patch(
            "myrm_agent_harness.toolkits.browser.doctor.checks._probe_browser_launch",
            side_effect=never_finishes,
        ),
    ):
        result = await _check_browser_launch()

    assert result.status == CheckStatus.ERROR
    assert "patchright not available" not in result.message
    assert "timed out" in result.message.lower()
    assert not result.message.endswith(":")


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
    from myrm_agent_harness.toolkits.browser.doctor import (
        CheckStatus,
        DoctorCheckResult,
        DoctorReport,
    )

    report = DoctorReport(
        checks={
            "memory": DoctorCheckResult(
                name="Memory",
                status=CheckStatus.WARNING,
                message="Low memory: 0.8 GB available",
                details={"available_gb": 0.8, "used_percent": 92.0},
            ),
            "disk": DoctorCheckResult(
                name="Disk",
                status=CheckStatus.ERROR,
                message="Low disk space: 0.2 GB available",
                details={"available_gb": 0.2, "used_percent": 98.0},
            ),
        },
        summary="0/2 checks passed, 1 warning, 1 error",
        overall_healthy=False,
        recommendations=[
            "Free up system memory",
            "Clean up /tmp or increase disk space",
        ],
    )

    output = format_report(report)
    assert "Browser Doctor" in output
    assert "·" in output
    assert "" in output
    assert "recommendation" in output.lower()
    assert isinstance(output, str)


async def test_check_extension_relay_requires_access_policy() -> None:
    """Relay ready without domains must not report OK."""
    import json

    from myrm_agent_harness.toolkits.browser.doctor import (
        CheckStatus,
        _check_extension_relay,
    )

    payload = json.dumps(
        {
            "relay_cdp_ready": True,
            "access_policy_valid": False,
            "auth_token_required": False,
            "auth_token_configured": True,
        }
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = payload
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.return_value = mock_response

    with patch(
        "myrm_agent_harness.toolkits.browser.doctor.checks.create_httpx_client",
        return_value=mock_client,
    ):
        result = await _check_extension_relay()

    assert result.status == CheckStatus.WARNING
    assert "access policy" in result.message.lower()
    assert result.fix is not None


async def test_check_extension_relay_ok_when_policy_valid() -> None:
    """Relay and access policy both ready should report OK."""
    import json

    from myrm_agent_harness.toolkits.browser.doctor import (
        CheckStatus,
        _check_extension_relay,
    )

    payload = json.dumps(
        {
            "relay_cdp_ready": True,
            "access_policy_valid": True,
            "auth_token_required": False,
            "auth_token_configured": True,
        }
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = payload
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.return_value = mock_response

    with patch(
        "myrm_agent_harness.toolkits.browser.doctor.checks.create_httpx_client",
        return_value=mock_client,
    ):
        result = await _check_extension_relay()

    assert result.status == CheckStatus.OK


async def test_check_extension_relay_non_dict_payload_graceful() -> None:
    """Non-dict JSON (e.g. gateway swallowing the endpoint) must degrade, not crash."""
    from myrm_agent_harness.toolkits.browser.doctor import (
        CheckStatus,
        _check_extension_relay,
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "[]"
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.return_value = mock_response

    with patch(
        "myrm_agent_harness.toolkits.browser.doctor.checks.create_httpx_client",
        return_value=mock_client,
    ):
        result = await _check_extension_relay()

    assert result.status == CheckStatus.WARNING
    assert "unexpected response format" in result.message.lower()
    assert result.fix is not None


@pytest.mark.asyncio
async def test_check_extension_relay_uses_custom_base_url() -> None:
    """An explicit base URL must drive the probe target, overriding defaults."""
    import json

    from myrm_agent_harness.toolkits.browser.doctor import (
        CheckStatus,
        _check_extension_relay,
    )

    payload = json.dumps(
        {
            "relay_cdp_ready": True,
            "access_policy_valid": True,
            "auth_token_required": False,
            "auth_token_configured": True,
        }
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = payload
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.return_value = mock_response

    with patch(
        "myrm_agent_harness.toolkits.browser.doctor.checks.create_httpx_client",
        return_value=mock_client,
    ):
        result = await _check_extension_relay(base_url="http://127.0.0.1:18080")

    assert result.status == CheckStatus.OK
    mock_client.get.assert_awaited_once_with("http://127.0.0.1:18080/api/v1/extension/setup-hints")


@pytest.mark.asyncio
async def test_run_doctor_forwards_extension_relay_base_url() -> None:
    """run_doctor must forward the base URL into the relay probe."""
    from myrm_agent_harness.toolkits.browser.doctor import (
        DoctorCheckResult,
    )

    async def fake_relay(base_url: str) -> DoctorCheckResult:
        assert base_url == "http://127.0.0.1:18080"
        return DoctorCheckResult(
            name="extension_relay",
            status=CheckStatus.WARNING,
            message="relay mock",
        )

    with patch(
        "myrm_agent_harness.toolkits.browser.doctor.checks._check_extension_relay",
        side_effect=fake_relay,
    ):
        report = await run_doctor(
            include_launch_test=False,
            include_orphan_check=False,
            extension_relay_base_url="http://127.0.0.1:18080",
        )

    assert report.checks["extension_relay"].message == "relay mock"


def test_check_memory_tight_warning() -> None:
    """Memory check warns when available memory is between 1 and 2 GB."""
    mock_psutil = MagicMock()
    mock_memory = MagicMock()
    mock_memory.available = int(1.5 * 1024**3)
    mock_memory.total = 8 * 1024**3
    mock_memory.percent = 82.0
    mock_psutil.virtual_memory.return_value = mock_memory

    with patch.dict("sys.modules", {"psutil": mock_psutil}):
        from importlib import reload

        import myrm_agent_harness.toolkits.browser.doctor as doctor_module

        reload(doctor_module)
        result = doctor_module._check_memory()

    assert result.status == CheckStatus.WARNING
    assert "Memory tight" in result.message


def test_check_disk_psutil_missing() -> None:
    """Disk check warns when psutil is unavailable."""
    from myrm_agent_harness.toolkits.browser.doctor import _check_disk

    with patch.dict("sys.modules", {"psutil": None}):
        result = _check_disk()

    assert result.status == CheckStatus.WARNING
    assert "psutil not installed" in result.message


def test_check_disk_low_error() -> None:
    """Disk check errors when free space drops below 0.5 GB."""
    mock_psutil = MagicMock()
    mock_usage = MagicMock()
    mock_usage.free = int(0.2 * 1024**3)
    mock_usage.percent = 98.0
    mock_psutil.disk_usage.return_value = mock_usage

    from myrm_agent_harness.toolkits.browser.doctor import _check_disk

    with patch.dict("sys.modules", {"psutil": mock_psutil}):
        result = _check_disk()

    assert result.status == CheckStatus.ERROR
    assert "Low disk space" in result.message


def test_check_disk_tight_warning() -> None:
    """Disk check warns when free space is between 0.5 and 1 GB."""
    mock_psutil = MagicMock()
    mock_usage = MagicMock()
    mock_usage.free = int(0.7 * 1024**3)
    mock_usage.percent = 90.0
    mock_psutil.disk_usage.return_value = mock_usage

    from myrm_agent_harness.toolkits.browser.doctor import _check_disk

    with patch.dict("sys.modules", {"psutil": mock_psutil}):
        result = _check_disk()

    assert result.status == CheckStatus.WARNING
    assert "Disk space tight" in result.message


def test_check_disk_scan_exception() -> None:
    """Disk check warns with the exception detail when the scan fails."""
    mock_psutil = MagicMock()
    mock_psutil.disk_usage.side_effect = OSError("no such mount")

    from myrm_agent_harness.toolkits.browser.doctor import _check_disk

    with patch.dict("sys.modules", {"psutil": mock_psutil}):
        result = _check_disk()

    assert result.status == CheckStatus.WARNING
    assert "Cannot check disk space" in result.message


@pytest.mark.asyncio
async def test_check_browser_launch_patchright_missing() -> None:
    """Launch check reports ERROR when patchright is not installed."""
    from myrm_agent_harness.toolkits.browser.doctor import _check_browser_launch

    with patch.dict(
        "sys.modules",
        {"patchright": None, "patchright.async_api": None},
    ):
        result = await _check_browser_launch()

    assert result.status == CheckStatus.ERROR
    assert "patchright not available" in result.message


@pytest.mark.asyncio
async def test_check_extension_relay_non_http_scheme() -> None:
    """Relay probe rejects non-http base URLs from the environment."""
    from myrm_agent_harness.toolkits.browser.doctor import _check_extension_relay

    with patch.dict(os.environ, {"MYRM_SERVER_URL": "ftp://localhost:8080"}):
        result = await _check_extension_relay()

    assert result.status == CheckStatus.WARNING
    assert "http(s) scheme" in result.message


@pytest.mark.asyncio
async def test_check_extension_relay_connection_error() -> None:
    """Relay probe degrades to WARNING when the server is unreachable."""
    import httpx

    from myrm_agent_harness.toolkits.browser.doctor import _check_extension_relay

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.side_effect = httpx.ConnectError("connection refused")

    with patch(
        "myrm_agent_harness.toolkits.browser.doctor.checks.create_httpx_client",
        return_value=mock_client,
    ):
        result = await _check_extension_relay()

    assert result.status == CheckStatus.WARNING
    assert "Server unreachable" in result.message


@pytest.mark.asyncio
async def test_check_extension_relay_probe_failure() -> None:
    """Relay probe reports unexpected failures with the exception detail."""
    from myrm_agent_harness.toolkits.browser.doctor import _check_extension_relay

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.side_effect = RuntimeError("boom")

    with patch(
        "myrm_agent_harness.toolkits.browser.doctor.checks.create_httpx_client",
        return_value=mock_client,
    ):
        result = await _check_extension_relay()

    assert result.status == CheckStatus.WARNING
    assert "probe failed" in result.message.lower()
    assert "boom" in result.message


@pytest.mark.asyncio
async def test_check_extension_relay_auth_token_missing() -> None:
    """Relay probe warns when the server requires an unconfigured auth token."""
    import json

    from myrm_agent_harness.toolkits.browser.doctor import _check_extension_relay

    payload = json.dumps(
        {
            "relay_cdp_ready": False,
            "access_policy_valid": False,
            "auth_token_required": True,
            "auth_token_configured": False,
        }
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = payload
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.return_value = mock_response

    with patch(
        "myrm_agent_harness.toolkits.browser.doctor.checks.create_httpx_client",
        return_value=mock_client,
    ):
        result = await _check_extension_relay()

    assert result.status == CheckStatus.WARNING
    assert "auth token missing" in result.message


@pytest.mark.asyncio
async def test_check_extension_relay_not_connected() -> None:
    """Relay probe warns when the extension is not connected at all."""
    import json

    from myrm_agent_harness.toolkits.browser.doctor import _check_extension_relay

    payload = json.dumps(
        {
            "relay_cdp_ready": False,
            "access_policy_valid": False,
            "auth_token_required": False,
            "auth_token_configured": False,
        }
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = payload
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.return_value = mock_response

    with patch(
        "myrm_agent_harness.toolkits.browser.doctor.checks.create_httpx_client",
        return_value=mock_client,
    ):
        result = await _check_extension_relay()

    assert result.status == CheckStatus.WARNING
    assert "not connected" in result.message


@pytest.mark.asyncio
async def test_run_doctor_summary_includes_error_and_missing() -> None:
    """Summary counts ERROR and MISSING checks and surfaces their fixes."""
    from myrm_agent_harness.toolkits.browser.doctor import DoctorCheckResult

    async def fake_relay(_base_url: str) -> DoctorCheckResult:
        return DoctorCheckResult(
            name="extension_relay",
            status=CheckStatus.ERROR,
            message="relay broken",
            fix="Restart the server",
        )

    async def fake_launch(_opts: object) -> DoctorCheckResult:
        return DoctorCheckResult(
            name="browser_launch",
            status=CheckStatus.MISSING,
            message="not tested",
        )

    def fake_orphan() -> DoctorCheckResult:
        return DoctorCheckResult(
            name="orphan_processes",
            status=CheckStatus.OK,
            message="clean",
        )

    with (
        patch(
            "myrm_agent_harness.toolkits.browser.doctor.checks._check_extension_relay",
            side_effect=fake_relay,
        ),
        patch(
            "myrm_agent_harness.toolkits.browser.doctor.checks._check_browser_launch",
            side_effect=fake_launch,
        ),
        patch(
            "myrm_agent_harness.toolkits.browser.doctor.checks.check_orphan_processes",
            side_effect=fake_orphan,
        ),
    ):
        report = await run_doctor(include_launch_test=True, include_orphan_check=True)

    assert "1 errors" in report.summary
    assert "1 missing" in report.summary
    assert report.overall_healthy is False
    assert "Restart the server" in report.recommendations


def test_format_report_full_sections() -> None:
    """CLI report renders cleanup and launch sections with fixes."""
    from myrm_agent_harness.toolkits.browser.doctor import (
        DoctorCheckResult,
        DoctorReport,
    )

    report = DoctorReport(
        checks={
            "patchright": DoctorCheckResult(
                name="patchright",
                status=CheckStatus.OK,
                message="patchright 1.50.0 installed",
            ),
            "memory": DoctorCheckResult(
                name="memory",
                status=CheckStatus.WARNING,
                message="Memory tight: 1.5 GB available (82% used)",
                fix="Consider closing other applications for better stability",
            ),
            "orphan_processes": DoctorCheckResult(
                name="orphan_processes",
                status=CheckStatus.WARNING,
                message="Found 2 orphan automation process(es)",
                fix="python -m myrm_agent_harness.toolkits.browser --cleanup-orphans --force",
            ),
            "extension_relay": DoctorCheckResult(
                name="extension_relay",
                status=CheckStatus.OK,
                message="Extension CDP relay is ready",
            ),
            "browser_launch": DoctorCheckResult(
                name="browser_launch",
                status=CheckStatus.ERROR,
                message="Browser executable not found",
                fix="Run 'patchright install chromium' to install the bundled browser",
            ),
        },
        summary="1/5 checks passed, 2 warnings, 1 error",
        overall_healthy=False,
        recommendations=[
            "python -m myrm_agent_harness.toolkits.browser --cleanup-orphans --force",
            "Run 'patchright install chromium' to install the bundled browser",
        ],
    )

    rendered = format_report(report)
    assert "Process Cleanup" in rendered
    assert "Launch Test" in rendered
    assert "Found 2 orphan automation" in rendered
    assert "patchright install chromium" in rendered
    assert "Consider closing other applications" in rendered


def test_format_report_with_colorama() -> None:
    """CLI report applies ANSI colors when colorama is available."""
    from myrm_agent_harness.toolkits.browser.doctor import (
        DoctorCheckResult,
        DoctorReport,
    )

    report = DoctorReport(
        checks={
            "patchright": DoctorCheckResult(
                name="patchright",
                status=CheckStatus.OK,
                message="patchright 1.50.0 installed",
            ),
        },
        summary="1/1 checks passed",
        overall_healthy=True,
    )

    with patch.dict("sys.modules", {"colorama": MagicMock()}):
        rendered = format_report(report)

    assert "Browser Doctor" in rendered
    assert "\033[92m" in rendered  # green status icon for OK checks
