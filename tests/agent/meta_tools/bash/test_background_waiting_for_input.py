"""Tests for background bash waiting_for_input heuristics."""

from __future__ import annotations

import time
from collections import deque
from typing import cast
from unittest.mock import MagicMock

from myrm_agent_harness.agent.meta_tools.bash._background_registry import (
    BackgroundProcessRegistry,
)
from myrm_agent_harness.agent.meta_tools.bash._background_registry_consume import (
    BackgroundRegistryEntry,
)
from myrm_agent_harness.agent.meta_tools.bash._background_types import (
    INPUT_WAIT_IDLE_SECONDS,
    BackgroundProcessInfo,
    compute_waiting_for_input,
)
from myrm_agent_harness.toolkits.code_execution.executors.models import (
    AsyncProcessProtocol,
)


def test_compute_waiting_for_input_requires_running_idle_open_stdin() -> None:
    started = 1000.0
    now = started + INPUT_WAIT_IDLE_SECONDS + 1.0
    assert (
        compute_waiting_for_input(
            status="running",
            last_output_at=started,
            started_at=started,
            stdin_closed=False,
            stdin_available=True,
            now=now,
        )
        is True
    )
    assert (
        compute_waiting_for_input(
            status="exited",
            last_output_at=started,
            started_at=started,
            stdin_closed=False,
            stdin_available=True,
            now=now,
        )
        is False
    )
    assert (
        compute_waiting_for_input(
            status="running",
            last_output_at=started,
            started_at=started,
            stdin_closed=True,
            stdin_available=True,
            now=now,
        )
        is False
    )
    assert (
        compute_waiting_for_input(
            status="running",
            last_output_at=now - 1.0,
            started_at=started,
            stdin_closed=False,
            stdin_available=True,
            now=now,
        )
        is False
    )


def test_registry_snapshot_sets_waiting_for_input() -> None:
    proc = MagicMock()
    proc.stdin = MagicMock()
    started = time.time() - INPUT_WAIT_IDLE_SECONDS - 5.0
    info = BackgroundProcessInfo(
        job_id="job-wait",
        pid=8801,
        command="python -c 'input()'",
        session_id="sess-wait",
        started_at=started,
        status="running",
        last_output_at=started,
    )
    entry = BackgroundRegistryEntry(
        info=info,
        proc=cast(AsyncProcessProtocol, proc),
        stdout_buffer=deque(),
        stderr_buffer=deque(),
    )
    snap = BackgroundProcessRegistry._snapshot(entry)
    assert snap.waiting_for_input is True


def test_registry_snapshot_clears_waiting_after_stdin_closed() -> None:
    proc = MagicMock()
    proc.stdin = MagicMock()
    started = time.time() - INPUT_WAIT_IDLE_SECONDS - 5.0
    info = BackgroundProcessInfo(
        job_id="job-closed",
        pid=8802,
        command="npm create vite",
        session_id="sess-closed",
        started_at=started,
        status="running",
        last_output_at=started,
    )
    entry = BackgroundRegistryEntry(
        info=info,
        proc=cast(AsyncProcessProtocol, proc),
        stdout_buffer=deque(),
        stderr_buffer=deque(),
        stdin_closed=True,
    )
    snap = BackgroundProcessRegistry._snapshot(entry)
    assert snap.waiting_for_input is False
