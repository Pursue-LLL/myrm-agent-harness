"""Chromium launched by the pool launcher is stamped and recognised as Chromium; the driver and this process are not."""

from __future__ import annotations

import asyncio
import contextlib
import os
import time

import psutil
import pytest

from myrm_agent_harness.toolkits.browser.doctor.orphans import _is_chromium_process
from myrm_agent_harness.toolkits.browser.pool.browser_launcher import BrowserLauncher
from myrm_agent_harness.toolkits.browser.process_owner import OWNER_ENV_VAR, OwnerState, read_owner_state
from tests.toolkits.browser._browser_available import chromium_available

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.skipif(not chromium_available(), reason="Chromium/Patchright not installed in this environment"),
]

_HELPER_STARTUP_TIMEOUT_S = 10.0


def _driver_of(parent: psutil.Process) -> psutil.Process:
    return next(proc for proc in parent.children(recursive=True) if "run-driver" in " ".join(proc.cmdline()))


async def _wait_for_browser_processes(driver: psutil.Process) -> list[psutil.Process]:
    """The browser main process and at least one helper; Chromium starts its helpers right after the main process."""
    deadline = time.monotonic() + _HELPER_STARTUP_TIMEOUT_S
    while True:
        processes = driver.children(recursive=True)
        if len(processes) >= 2 or time.monotonic() >= deadline:
            return processes
        await asyncio.sleep(0.1)


def _owner_states(processes: list[psutil.Process]) -> dict[int, OwnerState]:
    states: dict[int, OwnerState] = {}
    for proc in processes:
        with contextlib.suppress(psutil.NoSuchProcess):
            states[proc.pid] = read_owner_state(proc)
    return states


def _not_recognised_as_chromium(processes: list[psutil.Process]) -> list[str]:
    """Names of the running processes the orphan check would take for something other than Chromium."""
    return [proc.name() for proc in processes if proc.is_running() and not _is_chromium_process(proc)]


async def test_launched_chromium_is_stamped_and_nothing_else_is() -> None:
    launcher = BrowserLauncher(launch_options={"headless": True})
    instance = await launcher.create_browser()
    try:
        driver = _driver_of(psutil.Process())
        browser_processes = await _wait_for_browser_processes(driver)
        states = _owner_states(browser_processes)

        assert len(states) >= 2
        assert set(states.values()) == {OwnerState.OWNER_ALIVE}
        assert _not_recognised_as_chromium(browser_processes) == []
        assert read_owner_state(driver) is OwnerState.UNSTAMPED
        assert OWNER_ENV_VAR not in os.environ
    finally:
        with contextlib.suppress(Exception):
            await instance.browser.close()
        await launcher.shutdown()
