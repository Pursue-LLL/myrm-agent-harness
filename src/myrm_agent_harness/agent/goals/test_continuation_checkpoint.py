"""Tests for continuation_checkpoint — per-todo checkpoint guard."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.goals.continuation_checkpoint import (
    _CHECKPOINT_SNAPSHOT_KEY,
    check_todo_checkpoint,
)
from myrm_agent_harness.agent.goals.types import Goal, GoalBudget, GoalStatus

_PATCH_WS_ROOT = "myrm_agent_harness.agent.middlewares._session_context.get_workspace_root"


def _make_goal(
    checkpoint_mode: str = "per_todo",
    metadata: dict[str, Any] | None = None,
) -> Goal:
    return Goal(
        goal_id="g-test",
        session_id="s-test",
        objective="Test objective",
        status=GoalStatus.ACTIVE,
        checkpoint_mode=checkpoint_mode,
        budget=GoalBudget(max_turns=20),
        metadata=metadata or {},
    )


def _write_todos(workspace: str, todos: list[dict[str, str]]) -> None:
    progress_dir = Path(workspace) / ".myrm" / "progress"
    progress_dir.mkdir(parents=True, exist_ok=True)
    store = {"todos": todos}
    (progress_dir / "todos.json").write_text(json.dumps(store))


@pytest.mark.asyncio
async def test_skip_when_mode_none() -> None:
    goal = _make_goal(checkpoint_mode="none")
    provider = AsyncMock()
    result = await check_todo_checkpoint(provider, goal)
    assert result is None


@pytest.mark.asyncio
async def test_skip_when_no_workspace() -> None:
    goal = _make_goal()
    provider = AsyncMock()
    with patch(_PATCH_WS_ROOT, return_value=None):
        result = await check_todo_checkpoint(provider, goal)
    assert result is None


@pytest.mark.asyncio
async def test_skip_when_no_todos_file() -> None:
    goal = _make_goal()
    provider = AsyncMock()
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch(_PATCH_WS_ROOT, return_value=tmpdir):
            result = await check_todo_checkpoint(provider, goal)
    assert result is None


@pytest.mark.asyncio
async def test_skip_when_no_completed_todos() -> None:
    goal = _make_goal()
    provider = AsyncMock()
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_todos(tmpdir, [
            {"id": "t1", "content": "Step 1", "status": "pending"},
            {"id": "t2", "content": "Step 2", "status": "in_progress"},
        ])
        with patch(_PATCH_WS_ROOT, return_value=tmpdir):
            result = await check_todo_checkpoint(provider, goal)
    assert result is None


@pytest.mark.asyncio
async def test_pause_on_new_completed_todo() -> None:
    goal = _make_goal()
    provider = AsyncMock()
    provider.update_metadata = AsyncMock()
    provider.update_status = AsyncMock()

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_todos(tmpdir, [
            {"id": "t1", "content": "Build image", "status": "completed"},
            {"id": "t2", "content": "Run migration", "status": "pending"},
        ])
        with patch(_PATCH_WS_ROOT, return_value=tmpdir):
            result = await check_todo_checkpoint(provider, goal)

    assert result is not None
    assert result.verdict == "checkpoint_pause"
    assert result.should_continue is False
    assert "1 todo(s) completed" in result.reason
    assert "1/2" in result.reason

    provider.update_metadata.assert_called_once()
    meta_args = provider.update_metadata.call_args[0]
    assert meta_args[0] == "g-test"
    assert _CHECKPOINT_SNAPSHOT_KEY in meta_args[1]
    assert "t1" in meta_args[1][_CHECKPOINT_SNAPSHOT_KEY]

    provider.update_status.assert_called_once_with("g-test", GoalStatus.PAUSED)


@pytest.mark.asyncio
async def test_skip_when_same_completed_snapshot() -> None:
    goal = _make_goal(metadata={_CHECKPOINT_SNAPSHOT_KEY: ["t1"]})
    provider = AsyncMock()

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_todos(tmpdir, [
            {"id": "t1", "content": "Build image", "status": "completed"},
            {"id": "t2", "content": "Run migration", "status": "pending"},
        ])
        with patch(_PATCH_WS_ROOT, return_value=tmpdir):
            result = await check_todo_checkpoint(provider, goal)

    assert result is None
    provider.update_metadata.assert_not_called()


@pytest.mark.asyncio
async def test_detect_multiple_new_completions() -> None:
    goal = _make_goal(metadata={_CHECKPOINT_SNAPSHOT_KEY: ["t1"]})
    provider = AsyncMock()
    provider.update_metadata = AsyncMock()
    provider.update_status = AsyncMock()

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_todos(tmpdir, [
            {"id": "t1", "content": "Build image", "status": "completed"},
            {"id": "t2", "content": "Run migration", "status": "completed"},
            {"id": "t3", "content": "Health check", "status": "completed"},
            {"id": "t4", "content": "Verify", "status": "pending"},
        ])
        with patch(_PATCH_WS_ROOT, return_value=tmpdir):
            result = await check_todo_checkpoint(provider, goal)

    assert result is not None
    assert result.verdict == "checkpoint_pause"
    assert "2 todo(s) completed" in result.reason
    assert "3/4" in result.reason

    meta_args = provider.update_metadata.call_args[0]
    snapshot = meta_args[1][_CHECKPOINT_SNAPSHOT_KEY]
    assert set(snapshot) == {"t1", "t2", "t3"}


@pytest.mark.asyncio
async def test_pause_reason_includes_todo_names() -> None:
    goal = _make_goal()
    provider = AsyncMock()
    provider.update_metadata = AsyncMock()
    provider.update_status = AsyncMock()

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_todos(tmpdir, [
            {"id": "t1", "content": "Deploy service", "status": "completed"},
        ])
        with patch(_PATCH_WS_ROOT, return_value=tmpdir):
            await check_todo_checkpoint(provider, goal)

    meta_args = provider.update_metadata.call_args[0]
    pause_reason = meta_args[1]["pause_reason"]
    assert "Deploy service" in pause_reason
    assert "(1/1)" in pause_reason
