"""Tests for clearing the checkpoint thread an earlier process left under a delegation's subagent id.

A subagent waiting for approval keeps its thread across restarts. The new subagent that a lost approval journal
starts under the same id must begin from an empty thread, and clearing it must never fail the delegation.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import AsyncIterator
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import Checkpoint, CheckpointMetadata

from myrm_agent_harness.agent.sub_agents._manager_spawn import SubagentSpawnMixin
from myrm_agent_harness.agent.sub_agents.checkpointer import (
    SubagentSqliteCheckpointer,
    close_subagent_checkpointer,
    discard_stale_subagent_thread,
    get_subagent_checkpointer,
    reset_subagent_checkpointer,
)

_STALE: RunnableConfig = {"configurable": {"thread_id": "paused-before-restart"}}
_UNRELATED: RunnableConfig = {"configurable": {"thread_id": "unrelated"}}


@pytest.fixture(autouse=True)
async def _cleanup_checkpointer() -> AsyncIterator[None]:
    await close_subagent_checkpointer()
    reset_subagent_checkpointer()
    yield
    await close_subagent_checkpointer()
    reset_subagent_checkpointer()


def _checkpoint(checkpoint_id: str) -> Checkpoint:
    return {
        "v": 1,
        "ts": "2026-09-27T12:00:00Z",
        "id": checkpoint_id,
        "channel_values": {"hitl": True},
        "channel_versions": {"hitl": 1},
        "versions_seen": {},
        "pending_sends": [],
    }


async def _leave_paused_threads_behind(db_file: str) -> None:
    """Persist two threads the way an earlier process leaves them when it stops while subagents wait for approval."""
    meta: CheckpointMetadata = {"source": "loop", "step": 1, "writes": {}, "parents": {}}
    earlier_process = SubagentSqliteCheckpointer(db_file)
    await earlier_process.aput(_STALE, _checkpoint("cp_stale"), meta, {"hitl": 1})
    await earlier_process.aput(_UNRELATED, _checkpoint("cp_other"), meta, {"hitl": 1})
    await earlier_process.aclose()


@pytest.mark.asyncio
async def test_a_thread_left_by_an_earlier_process_is_dropped_before_a_new_subagent_reuses_its_id(tmp_path: Path):
    """After a restart nothing has opened the shared store yet, so the thread is only found by opening it."""
    db_file = str(tmp_path / "restart.sqlite")
    await _leave_paused_threads_behind(db_file)

    with patch.dict(os.environ, {"SUBAGENT_CHECKPOINT_DB_PATH": db_file}):
        reset_subagent_checkpointer()
        await discard_stale_subagent_thread("paused-before-restart")
        await discard_stale_subagent_thread("never-existed")
        survivors = get_subagent_checkpointer()

        assert await survivors.aget_tuple(_STALE) is None
        assert await survivors.aget_tuple(_UNRELATED) is not None


@pytest.mark.asyncio
async def test_an_unreadable_stale_thread_is_dropped_instead_of_failing_the_delegation(tmp_path: Path):
    """A blob an earlier version wrote can fail to load; clearing it must still let the new subagent start."""
    db_file = str(tmp_path / "restart.sqlite")
    await _leave_paused_threads_behind(db_file)
    with closing(sqlite3.connect(db_file)) as raw:
        raw.execute(
            "UPDATE checkpoints SET checkpoint = ? WHERE thread_id = ?",
            (b"\x80\x04not-a-checkpoint", "paused-before-restart"),
        )
        raw.commit()

    with patch.dict(os.environ, {"SUBAGENT_CHECKPOINT_DB_PATH": db_file}):
        reset_subagent_checkpointer()
        await discard_stale_subagent_thread("paused-before-restart")
        survivors = get_subagent_checkpointer()

        assert await survivors.aget_tuple(_UNRELATED) is not None
    with closing(sqlite3.connect(db_file)) as raw:
        remaining = raw.execute("SELECT thread_id FROM checkpoints").fetchall()
    assert remaining == [("unrelated",)]


@pytest.mark.asyncio
async def test_the_journal_of_a_manager_clears_the_thread_a_new_subagent_would_inherit(tmp_path: Path):
    """The cleanup has to be wired where delegations are journaled, not merely exist as a function."""
    db_file = str(tmp_path / "restart.sqlite")
    await _leave_paused_threads_behind(db_file)

    with patch.dict(os.environ, {"SUBAGENT_CHECKPOINT_DB_PATH": db_file}):
        reset_subagent_checkpointer()
        await SubagentSpawnMixin().approval_journal.clear_stale_thread("paused-before-restart")
        survivors = get_subagent_checkpointer()

        assert await survivors.aget_tuple(_STALE) is None
        assert await survivors.aget_tuple(_UNRELATED) is not None
