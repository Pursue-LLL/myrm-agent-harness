"""Context cleanup and the file access tracker follow a context root configured after import.

Without a ``/persistent`` mount (local dev) the server rebinds ``execution_paths.CONTEXT_ROOT`` at
startup, and every writer derives its paths from the new value. Cleanup and the access tracker must
read the same value at call time: a copy taken at import time makes cleanup scan a directory nothing
writes to, and points the tracker at a path that does not exist on the machine.
"""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.context_management.infra.session_lock import (
    reset_current_chat_id,
    set_current_chat_id,
)
from myrm_agent_harness.agent.meta_tools.file_ops.observers.tracker_observer import TrackerObserver
from myrm_agent_harness.runtime.context.cleanup_ops import (
    cleanup_orphan_context_files_async,
    cleanup_session_context_files,
)
from myrm_agent_harness.runtime.context.file_access_tracker import (
    FileAccessTracker,
    get_file_access_tracker,
    reset_tracker,
)
from myrm_agent_harness.runtime.paths import execution_paths
from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor

_FORTY_DAYS_S = 40 * 86400


@pytest.fixture
def local_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The context root as the local-dev startup shim rebinds it."""
    root = tmp_path / "harness" / ".context"
    root.mkdir(parents=True)
    monkeypatch.setattr(execution_paths, "CONTEXT_ROOT", str(root))
    return root


@pytest.fixture
async def fresh_tracker() -> AsyncIterator[None]:
    await reset_tracker()
    yield
    await reset_tracker()


def _write_aged(path: Path, age_s: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    stamp = time.time() - age_s
    os.utime(path, (stamp, stamp))


@pytest.mark.asyncio
async def test_orphan_cleanup_scans_the_rebound_context_root(local_root: Path) -> None:
    stale = local_root / "old-chat" / "evicted" / "output.txt"
    _write_aged(stale, _FORTY_DAYS_S)
    tracker = AsyncMock()
    tracker.batch_check_files.return_value = {}

    removed = await cleanup_orphan_context_files_async(access_tracker=tracker)

    assert removed == 1
    assert not stale.exists()


@pytest.mark.asyncio
async def test_session_cleanup_acts_on_the_rebound_context_root(local_root: Path) -> None:
    session_dir = local_root / "chat_deleted"
    _write_aged(session_dir / "evicted" / "output.txt", 60)
    executor = MagicMock()
    executor.workspace_path = str(local_root.parent / "workspace")
    executor.execute_bash = AsyncMock()

    await cleanup_session_context_files("chat_deleted", cast(CodeExecutor, executor))

    executor.execute_bash.assert_awaited_once()
    script = executor.execute_bash.await_args.args[0].code
    assert repr(str(local_root)) in script
    assert repr(str(session_dir)) in script


def test_a_tracker_without_an_explicit_path_uses_the_rebound_context_root(local_root: Path) -> None:
    assert FileAccessTracker()._db_path == str(local_root / ".file_access.db")


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_tracker")
async def test_the_shared_tracker_keeps_its_database_inside_the_rebound_context_root(local_root: Path) -> None:
    tracker = await get_file_access_tracker()
    tracked = local_root / "chat_a" / "compacted" / "out.txt"
    await tracker.record_access(str(tracked), session_id="chat_a")

    assert (local_root / ".file_access.db").is_file()
    assert await tracker.get_last_access(str(tracked)) is not None


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_tracker")
async def test_a_file_the_agent_read_survives_cleanup_while_an_unread_one_of_the_same_age_does_not(
    local_root: Path,
) -> None:
    read = local_root / "chat_a" / "compacted" / "read.txt"
    unread = local_root / "chat_a" / "compacted" / "unread.txt"
    _write_aged(read, _FORTY_DAYS_S)
    _write_aged(unread, _FORTY_DAYS_S)

    token = set_current_chat_id("chat_a")
    try:
        await TrackerObserver().on_file_viewed(str(read))
    finally:
        reset_current_chat_id(token)

    removed = await cleanup_orphan_context_files_async(access_tracker=await get_file_access_tracker())

    assert removed == 1
    assert read.exists()
    assert not unread.exists()
