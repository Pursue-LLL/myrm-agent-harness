"""Shared fixtures for browser tests."""

from __future__ import annotations

import atexit
from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from tests.toolkits.browser._stamped_processes import StampedProcesses


@pytest.fixture
def stamped_processes() -> Iterator[StampedProcesses]:
    """Real child processes carrying a chosen ownership stamp; every one is killed at teardown."""
    from tests.toolkits.browser._stamped_processes import StampedProcesses

    with StampedProcesses() as processes:
        yield processes


def _cleanup_browser_child_processes() -> None:
    from tests.support.browser_process_cleanup import terminate_browser_processes_in_tree

    terminate_browser_processes_in_tree()


atexit.register(_cleanup_browser_child_processes)
