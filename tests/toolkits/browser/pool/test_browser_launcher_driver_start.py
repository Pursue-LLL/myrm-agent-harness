"""Starting the Playwright driver must leave the process environment untouched."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.pool.browser_launcher import BrowserLauncher
from myrm_agent_harness.toolkits.browser.process_owner import OWNER_ENV_VAR

pytestmark = pytest.mark.asyncio


async def test_driver_start_does_not_expose_the_stamp_to_other_subprocesses() -> None:
    """A process another task spawns while the driver starts would inherit the stamp and later look like a leftover."""
    stamp_present_during_start: list[bool] = []

    async def start() -> MagicMock:
        stamp_present_during_start.append(OWNER_ENV_VAR in os.environ)
        return MagicMock()

    launcher = BrowserLauncher(launch_options={"headless": True})
    with patch("patchright.async_api.async_playwright", return_value=MagicMock(start=start)):
        await launcher._ensure_playwright()

    assert stamp_present_during_start == [False]
