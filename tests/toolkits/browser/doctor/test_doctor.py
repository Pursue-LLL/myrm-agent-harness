"""Unit tests for the browser doctor orchestrator and report rendering."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.doctor import (
    CheckStatus,
    DoctorCheckResult,
    DoctorReport,
    check_memory,
    format_report,
    run_doctor,
)
from myrm_agent_harness.toolkits.browser.doctor.checks import _check_patchright


def test_format_report_includes_camoufox() -> None:
    """Environment section in CLI report must list camoufox when checked."""

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


def _stub_check(name: str, status: CheckStatus = CheckStatus.OK, fix: str = "") -> DoctorCheckResult:
    return DoctorCheckResult(name=name, status=status, message=f"{name} stub", fix=fix)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("launch_status", "expect_healthy", "expect_recommendations"),
    [
        (CheckStatus.OK, True, []),
        (CheckStatus.ERROR, False, ["fix the launch"]),
    ],
)
async def test_run_doctor_with_launch_reports_launch_outcome(
    launch_status: CheckStatus,
    expect_healthy: bool,
    expect_recommendations: list[str],
) -> None:
    """The verdict follows the launch result; host resources are pinned so it cannot depend on the machine."""
    launch = _stub_check(
        "browser_launch", launch_status, fix="fix the launch" if launch_status != CheckStatus.OK else ""
    )
    with (
        patch(
            "myrm_agent_harness.toolkits.browser.doctor.checks._check_patchright",
            return_value=_stub_check("patchright"),
        ),
        patch("myrm_agent_harness.toolkits.browser.doctor.checks.check_memory", return_value=_stub_check("memory")),
        patch("myrm_agent_harness.toolkits.browser.doctor.checks.check_disk", return_value=_stub_check("disk")),
        patch("myrm_agent_harness.toolkits.browser.doctor.checks.check_browser_launch", return_value=launch),
    ):
        report = await run_doctor(include_launch_test=True, include_orphan_check=False)

    assert report.checks["browser_launch"] is launch
    assert report.overall_healthy is expect_healthy
    assert report.recommendations == expect_recommendations


@pytest.mark.asyncio
async def test_run_doctor_runs_extra_orphan_and_launch_concurrently() -> None:
    """Host-supplied, orphan and launch checks must run concurrently and all land in the report."""

    host = DoctorCheckResult(
        name="host_probe",
        status=CheckStatus.WARNING,
        message="host mock",
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
    host_completed = asyncio.Event()

    async def fake_host_probe() -> DoctorCheckResult:
        started.append("host")
        await host_completed.wait()
        return host

    def fake_orphan() -> DoctorCheckResult:
        started.append("orphan")
        return orphan

    async def fake_launch(
        _launch_options: dict[str, object] | None,
    ) -> DoctorCheckResult:
        started.append("launch")
        await asyncio.sleep(0)
        host_completed.set()
        return launch

    with (
        patch(
            "myrm_agent_harness.toolkits.browser.doctor.checks.check_orphan_processes",
            side_effect=fake_orphan,
        ),
        patch(
            "myrm_agent_harness.toolkits.browser.doctor.checks.check_browser_launch",
            side_effect=fake_launch,
        ),
    ):
        report = await run_doctor(
            include_launch_test=True,
            include_orphan_check=True,
            extra_checks={"host_probe": fake_host_probe()},
        )

    # The host probe blocks until the launch check has started (otherwise this test deadlocks);
    # the orphan scan runs in the same concurrent batch.
    assert "host" in started
    assert "launch" in started
    assert "orphan" in started
    assert report.checks["host_probe"] is host
    assert report.checks["browser_launch"] is launch
    assert report.checks["orphan_processes"] is orphan


def test_format_report() -> None:
    """Test report formatting."""

    report = DoctorReport(
        checks={
            "patchright": _check_patchright(),
            "memory": check_memory(),
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
            "Free up disk space or clean up temporary files",
        ],
    )

    output = format_report(report)
    assert "Browser Doctor" in output
    assert "·" in output
    assert "" in output
    assert "recommendation" in output.lower()
    assert isinstance(output, str)


@pytest.mark.asyncio
async def test_run_doctor_rejects_extra_check_that_shadows_a_builtin() -> None:
    """A host check may not silently replace a built-in check of the same name."""
    shadow = _stub_check("memory")

    async def shadowing_check() -> DoctorCheckResult:
        return shadow

    probe = shadowing_check()
    with pytest.raises(ValueError, match="memory"):
        await run_doctor(include_launch_test=False, include_orphan_check=False, extra_checks={"memory": probe})
    probe.close()


@pytest.mark.asyncio
async def test_run_doctor_summary_includes_error_and_missing() -> None:
    """Summary counts ERROR and MISSING checks (host checks included) and surfaces their fixes."""

    async def fake_host_probe() -> DoctorCheckResult:
        return DoctorCheckResult(
            name="host_probe",
            status=CheckStatus.ERROR,
            message="host broken",
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
            "myrm_agent_harness.toolkits.browser.doctor.checks.check_browser_launch",
            side_effect=fake_launch,
        ),
        patch(
            "myrm_agent_harness.toolkits.browser.doctor.checks.check_orphan_processes",
            side_effect=fake_orphan,
        ),
    ):
        report = await run_doctor(
            include_launch_test=True,
            include_orphan_check=True,
            extra_checks={"host_probe": fake_host_probe()},
        )

    assert "1 errors" in report.summary
    assert "1 missing" in report.summary
    assert report.overall_healthy is False
    assert "Restart the server" in report.recommendations


def test_format_report_full_sections() -> None:
    """CLI report renders cleanup and launch sections with fixes."""

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
