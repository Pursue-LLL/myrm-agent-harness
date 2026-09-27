"""Tests for subagent crash-resilient SQLite checkpointer persistence and thread isolation.

Verifies:
1. Environment-aware database path resolution (Volume vs memory isolation).
2. Lazy asynchronous initialization and operation (aput, aget_tuple, adelete_thread).
3. Memory fallback mode when CHECKPOINTER_MODE=memory.
4. Thread isolation between distinct subagent tasks (thread_id == task_id).
5. Terminal status hygiene and PENDING_APPROVAL thread retention.
6. Cross-restart resumption: state persisted to disk survives connection close and restarts.
7. Lifecycle management (close_subagent_checkpointer & reset_subagent_checkpointer).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import Checkpoint, CheckpointMetadata
from langgraph.checkpoint.memory import InMemorySaver

from myrm_agent_harness.agent.sub_agents.checkpointer import (
    SubagentSqliteCheckpointer,
    _drop_finished_subagent_thread,
    close_subagent_checkpointer,
    get_subagent_checkpointer,
    reset_subagent_checkpointer,
    resolve_subagent_checkpoint_db_path,
)
from myrm_agent_harness.agent.sub_agents.types import SubAgentStatus

if TYPE_CHECKING:
    pass


@pytest.fixture(autouse=True)
async def _cleanup_checkpointer():
    """Ensure checkpointer is clean before and after each test."""
    await close_subagent_checkpointer()
    reset_subagent_checkpointer()
    yield
    await close_subagent_checkpointer()
    reset_subagent_checkpointer()


@pytest.mark.asyncio
async def test_resolve_subagent_checkpoint_db_path_explicit():
    """Explicit SUBAGENT_CHECKPOINT_DB_PATH overrides everything."""
    with patch.dict(os.environ, {"SUBAGENT_CHECKPOINT_DB_PATH": "/custom/path.sqlite"}):
        assert resolve_subagent_checkpoint_db_path() == "/custom/path.sqlite"


@pytest.mark.asyncio
async def test_resolve_subagent_checkpoint_db_path_volume():
    """MYRM_DATA_DIR routes to Volume when not in active pytest isolation."""
    env = {"MYRM_DATA_DIR": "/volume/data"}
    with patch.dict(os.environ, env, clear=True):
        assert resolve_subagent_checkpoint_db_path() == "/volume/data/subagent_checkpoints.sqlite"


@pytest.mark.asyncio
async def test_memory_mode_fallback():
    """Setting CHECKPOINTER_MODE=memory returns InMemorySaver."""
    with patch.dict(os.environ, {"CHECKPOINTER_MODE": "memory"}):
        reset_subagent_checkpointer()
        saver = get_subagent_checkpointer()
        assert isinstance(saver, InMemorySaver)


@pytest.mark.asyncio
async def test_subagent_sqlite_operations(tmp_path: Path):
    """Verify standard CRUD and delete operations on SubagentSqliteCheckpointer."""
    db_file = str(tmp_path / "subagent_test.sqlite")
    checkpointer = SubagentSqliteCheckpointer(db_file)

    config: RunnableConfig = {"configurable": {"thread_id": "task_alpha"}}
    checkpoint: Checkpoint = {
        "v": 1,
        "ts": "2026-09-27T12:00:00Z",
        "id": "cp_01",
        "channel_values": {"output": "interrupted for approval"},
        "channel_versions": {"output": 1},
        "versions_seen": {},
        "pending_sends": [],
    }
    metadata: CheckpointMetadata = {
        "source": "loop",
        "step": 1,
        "writes": {},
        "parents": {},
    }

    # 1. Put
    saved_config = await checkpointer.aput(config, checkpoint, metadata, {"output": 1})
    assert saved_config["configurable"]["checkpoint_id"] == "cp_01"

    # 2. Get
    loaded = await checkpointer.aget_tuple(config)
    assert loaded is not None
    assert loaded.checkpoint["channel_values"]["output"] == "interrupted for approval"

    # 3. Delete thread (hygiene)
    await checkpointer.adelete_thread("task_alpha")
    after_delete = await checkpointer.aget_tuple(config)
    assert after_delete is None

    await checkpointer.aclose()


@pytest.mark.asyncio
async def test_thread_isolation_between_subagents(tmp_path: Path):
    """Different task_ids must have independent state in the same SQLite store."""
    db_file = str(tmp_path / "subagent_isolation.sqlite")
    checkpointer = SubagentSqliteCheckpointer(db_file)

    cfg1: RunnableConfig = {"configurable": {"thread_id": "task_1"}}
    cfg2: RunnableConfig = {"configurable": {"thread_id": "task_2"}}

    cp1: Checkpoint = {
        "v": 1,
        "ts": "2026-09-27T12:00:00Z",
        "id": "cp_1",
        "channel_values": {"msg": "subagent 1 state"},
        "channel_versions": {"msg": 1},
        "versions_seen": {},
        "pending_sends": [],
    }
    cp2: Checkpoint = {
        "v": 1,
        "ts": "2026-09-27T12:00:01Z",
        "id": "cp_2",
        "channel_values": {"msg": "subagent 2 state"},
        "channel_versions": {"msg": 1},
        "versions_seen": {},
        "pending_sends": [],
    }
    meta: CheckpointMetadata = {"source": "loop", "step": 1, "writes": {}, "parents": {}}

    await checkpointer.aput(cfg1, cp1, meta, {"msg": 1})
    await checkpointer.aput(cfg2, cp2, meta, {"msg": 1})

    t1 = await checkpointer.aget_tuple(cfg1)
    t2 = await checkpointer.aget_tuple(cfg2)
    assert t1 is not None and t1.checkpoint["channel_values"]["msg"] == "subagent 1 state"
    assert t2 is not None and t2.checkpoint["channel_values"]["msg"] == "subagent 2 state"

    # Deleting task_1 does not affect task_2
    await checkpointer.adelete_thread("task_1")
    assert await checkpointer.aget_tuple(cfg1) is None
    assert await checkpointer.aget_tuple(cfg2) is not None

    await checkpointer.aclose()


@pytest.mark.asyncio
async def test_cross_restart_persistence_and_resumption(tmp_path: Path):
    """Simulate container/process death and verify state can be read by a new checkpointer instance."""
    db_file = str(tmp_path / "persistent_subagents.sqlite")

    # Instance 1: subagent suspends in PENDING_APPROVAL
    inst1 = SubagentSqliteCheckpointer(db_file)
    task_id = "task_restart_01"
    config: RunnableConfig = {"configurable": {"thread_id": task_id}}
    checkpoint: Checkpoint = {
        "v": 1,
        "ts": "2026-09-27T12:00:00Z",
        "id": "cp_hitl_interrupt",
        "channel_values": {"pending_command": "rm -rf /untrusted/cache"},
        "channel_versions": {"pending_command": 1},
        "versions_seen": {},
        "pending_sends": [],
    }
    metadata: CheckpointMetadata = {"source": "loop", "step": 5, "writes": {}, "parents": {}}
    await inst1.aput(config, checkpoint, metadata, {"pending_command": 1})

    # Kill instance 1 (process exit / sandbox restart)
    await inst1.aclose()

    # Instance 2: new process starts up, loads the same persistent SQLite file
    inst2 = SubagentSqliteCheckpointer(db_file)
    resumed = await inst2.aget_tuple(config)
    assert resumed is not None
    assert resumed.checkpoint["channel_values"]["pending_command"] == "rm -rf /untrusted/cache"

    await inst2.aclose()


@pytest.mark.asyncio
async def test_terminal_hygiene_and_pending_approval_retention(tmp_path: Path):
    """_drop_finished_subagent_thread drops non-approval terminals and retains PENDING_APPROVAL."""
    db_file = str(tmp_path / "hygiene.sqlite")
    with patch.dict(os.environ, {"SUBAGENT_CHECKPOINT_DB_PATH": db_file}):
        reset_subagent_checkpointer()
        checkpointer = get_subagent_checkpointer()

        task_id = "task_approval_gate"
        cfg: RunnableConfig = {"configurable": {"thread_id": task_id}}
        cp: Checkpoint = {
            "v": 1,
            "ts": "2026-09-27T12:00:00Z",
            "id": "cp_gate",
            "channel_values": {"hitl": True},
            "channel_versions": {"hitl": 1},
            "versions_seen": {},
            "pending_sends": [],
        }
        meta: CheckpointMetadata = {"source": "loop", "step": 1, "writes": {}, "parents": {}}
        await checkpointer.aput(cfg, cp, meta, {"hitl": 1})

        # 1. PENDING_APPROVAL: must NOT delete
        await _drop_finished_subagent_thread(task_id, SubAgentStatus.PENDING_APPROVAL)
        assert await checkpointer.aget_tuple(cfg) is not None

        # String variant: must NOT delete
        await _drop_finished_subagent_thread(task_id, "pending_approval")
        assert await checkpointer.aget_tuple(cfg) is not None

        # 2. Terminal COMPLETED: must drop thread
        await _drop_finished_subagent_thread(task_id, SubAgentStatus.COMPLETED)
        assert await checkpointer.aget_tuple(cfg) is None

        await close_subagent_checkpointer()
