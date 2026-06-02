"""Integration tests for browser launch check in doctor module."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.browser.doctor import CheckStatus, run_doctor

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_run_doctor_with_browser_launch_test():
    """Should successfully launch browser and report OK status."""
    report = await run_doctor(include_launch_test=True, include_orphan_check=False)

    assert "browser_launch" in report.checks
    launch_check = report.checks["browser_launch"]
    assert launch_check.status == CheckStatus.OK
    assert "successful" in launch_check.message.lower()


async def test_run_doctor_with_custom_launch_options():
    """Should accept custom launch options and report OK."""
    report = await run_doctor(
        include_launch_test=True,
        include_orphan_check=False,
        launch_options={"headless": True, "args": ["--no-sandbox"]},
    )

    assert "browser_launch" in report.checks
    launch_check = report.checks["browser_launch"]
    assert launch_check.status == CheckStatus.OK
