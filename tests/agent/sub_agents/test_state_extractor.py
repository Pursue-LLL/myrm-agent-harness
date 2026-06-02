"""Tests for subagent state extraction utilities."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.sub_agents.checkpoint.state_extractor import (
    extract_subagent_state_async,
    extract_subagent_state_sync,
    restore_subagent_state,
)


class _FakeStatus(Enum):
    COMPLETED = "completed"
    RUNNING = "running"


@dataclass
class _FakeTokenUsage:
    total_tokens: int = 100

    def to_dict(self) -> dict[str, int]:
        return {"total_tokens": self.total_tokens}


@dataclass
class _FakeRunStats:
    token_usage: _FakeTokenUsage | None = None
    duration_seconds: float = 5.0
    status: _FakeStatus | None = _FakeStatus.COMPLETED


class _FakeAgent:
    """Minimal agent stub for state extraction tests."""

    def __init__(
        self, last_context: dict[str, object] | None = None, last_run_stats: _FakeRunStats | None = None
    ) -> None:
        self._last_context = last_context
        self.last_run_stats = last_run_stats


# =========================================================================
# extract_subagent_state_sync
# =========================================================================


class TestExtractStateSync:
    def test_extracts_context_from_last_context(self) -> None:
        agent = _FakeAgent(
            last_context={
                "session_id": "s1",
            }
        )
        state = extract_subagent_state_sync(agent, "task-1")  # type: ignore[arg-type]
        assert state["context"] == {
            "session_id": "s1",
        }

    def test_extracts_stats_from_last_run_stats(self) -> None:
        agent = _FakeAgent(last_run_stats=_FakeRunStats(token_usage=_FakeTokenUsage(200), duration_seconds=10.0))
        state = extract_subagent_state_sync(agent, "task-1")  # type: ignore[arg-type]
        assert state["stats"]["duration_seconds"] == 10.0
        assert state["stats"]["token_usage"]["total_tokens"] == 200
        assert state["progress"] == 1.0

    def test_progress_half_when_no_status(self) -> None:
        agent = _FakeAgent(last_run_stats=_FakeRunStats(token_usage=None, duration_seconds=1.0, status=None))
        state = extract_subagent_state_sync(agent, "task-1")  # type: ignore[arg-type]
        assert state["progress"] == 0.5

    def test_empty_agent_returns_defaults(self) -> None:
        agent = _FakeAgent()
        state = extract_subagent_state_sync(agent, "task-1")  # type: ignore[arg-type]
        assert state["messages"] == []
        assert state["context"] == {}
        assert state["stats"] == {}
        assert state["progress"] == 0.0
        assert state["last_tool"] is None

    def test_none_last_context_treated_as_empty(self) -> None:
        agent = _FakeAgent(last_context=None)
        state = extract_subagent_state_sync(agent, "task-1")  # type: ignore[arg-type]
        assert state["context"] == {}

    def test_sync_messages_always_empty(self) -> None:
        """Sync extraction cannot access LangChain messages."""
        agent = _FakeAgent(last_context={"workspace_path": "/tmp"}, last_run_stats=_FakeRunStats())
        state = extract_subagent_state_sync(agent, "task-1")  # type: ignore[arg-type]
        assert state["messages"] == []

    def test_token_usage_none_handled(self) -> None:
        agent = _FakeAgent(last_run_stats=_FakeRunStats(token_usage=None))
        state = extract_subagent_state_sync(agent, "task-1")  # type: ignore[arg-type]
        assert state["stats"]["token_usage"] == {}


# =========================================================================
# extract_subagent_state_async
# =========================================================================


class TestExtractStateAsync:
    @pytest.mark.asyncio
    async def test_async_extraction_via_checkpoint_state(self) -> None:
        agent = _FakeAgent()
        agent.get_checkpoint_state = AsyncMock(  # type: ignore[attr-defined]
            return_value={
                "messages": [{"role": "user", "content": "hi"}],
                "context": {"key": "val"},
                "progress": 0.8,
                "last_tool": "browser",
            }
        )
        state = await extract_subagent_state_async(agent, "task-1")  # type: ignore[arg-type]
        assert state["progress"] == 0.8
        assert state["last_tool"] == "browser"
        assert len(state["messages"]) == 1

    @pytest.mark.asyncio
    async def test_async_falls_back_on_failure(self) -> None:
        agent = _FakeAgent(last_context={"session_id": "s1"}, last_run_stats=_FakeRunStats())
        agent.get_checkpoint_state = AsyncMock(  # type: ignore[attr-defined]
            side_effect=RuntimeError("checkpointer unavailable")
        )
        state = await extract_subagent_state_async(agent, "task-1")  # type: ignore[arg-type]
        assert state["messages"] == []
        assert state["context"]["session_id"] == "s1"
        assert state["progress"] == 1.0


# =========================================================================
# restore_subagent_state (placeholder)
# =========================================================================


class TestRestoreState:
    @pytest.mark.asyncio
    async def test_restore_logs_warning(self) -> None:
        """restore_subagent_state is a placeholder — just verify no crash."""
        agent = _FakeAgent()
        await restore_subagent_state(agent, {"messages": []})  # type: ignore[arg-type]
