"""Tests for background bash waiting_for_input heuristics."""

from __future__ import annotations

import time
from collections import deque
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.meta_tools.bash._background.consume import (
    BackgroundRegistryEntry,
)
from myrm_agent_harness.agent.meta_tools.bash._background.registry import (
    BackgroundProcessRegistry,
    get_background_registry,
)
from myrm_agent_harness.agent.meta_tools.bash._background.types import (
    INPUT_WAIT_IDLE_SECONDS,
    BackgroundProcessInfo,
    compute_waiting_for_input,
)
from myrm_agent_harness.agent.meta_tools.bash.bash_process_tools import (
    create_bash_process_tool,
)
from myrm_agent_harness.toolkits.code_execution.executors.models import (
    AsyncProcessProtocol,
)


@pytest.fixture(autouse=True)
def _clear_registry() -> None:
    registry = get_background_registry()
    registry._entries.clear()  # type: ignore[attr-defined]
    yield
    registry._entries.clear()  # type: ignore[attr-defined]


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
    assert snap.stdin_closed is True


def test_registry_snapshot_exposes_stdin_closed_on_running_job() -> None:
    proc = MagicMock()
    proc.stdin = MagicMock()
    info = BackgroundProcessInfo(
        job_id="job-open-stdin",
        pid=8803,
        command="npm create vite",
        session_id="sess-open",
        started_at=time.time(),
        status="running",
    )
    entry = BackgroundRegistryEntry(
        info=info,
        proc=cast(AsyncProcessProtocol, proc),
        stdout_buffer=deque(),
        stderr_buffer=deque(),
        stdin_closed=False,
    )
    snap = BackgroundProcessRegistry._snapshot(entry)
    assert snap.stdin_closed is False
    payload = snap.to_dict()
    assert payload.get("stdin_closed") is False


@pytest.mark.asyncio
async def test_bash_process_output_exposes_waiting_for_input_and_hint() -> None:
    registry = get_background_registry()
    proc = MagicMock()
    proc.stdin = MagicMock()
    proc.stdout = MagicMock()
    proc.stderr = MagicMock()
    proc.wait = AsyncMock(return_value=0)
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc._proc = MagicMock(pid=8810)

    await registry.register(
        cast(AsyncProcessProtocol, proc),
        command="python -c 'input()'",
        session_id="sess-output-wait",
    )
    with registry._lock:  # type: ignore[attr-defined]
        entry = registry._entries[8810]
        entry.info.last_output_at = time.time() - INPUT_WAIT_IDLE_SECONDS - 2.0
        entry.stdout_buffer.append((1, "Password:"))

    tool = create_bash_process_tool()
    config = {"configurable": {"context": {"session_id": "sess-output-wait"}}}
    result = await tool.ainvoke({"action": "output", "pid": 8810}, config=config)
    content = result["content"]
    assert content["waiting_for_input"] is True
    assert "input_wait_hint" in content
    assert "submit_stdin" in str(content["input_wait_hint"])
