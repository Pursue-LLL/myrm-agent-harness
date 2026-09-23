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
    """Mirrors the real ``AgentRunStatistics`` field names.

    Uses ``total_duration_seconds`` / ``completion_status`` because the
    extraction path reads those; a fake with invented names would pass while
    production raised ``AttributeError``.
    """

    token_usage: _FakeTokenUsage | None = None
    total_duration_seconds: float = 5.0
    completion_status: _FakeStatus | None = _FakeStatus.COMPLETED


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
        agent = _FakeAgent(
            last_run_stats=_FakeRunStats(
                token_usage=_FakeTokenUsage(200), total_duration_seconds=10.0
            )
        )
        state = extract_subagent_state_sync(agent, "task-1")  # type: ignore[arg-type]
        assert state["stats"]["duration_seconds"] == 10.0
        assert state["stats"]["token_usage"]["total_tokens"] == 200
        assert state["progress"] == 1.0

    def test_progress_half_when_no_status(self) -> None:
        agent = _FakeAgent(
            last_run_stats=_FakeRunStats(
                token_usage=None, total_duration_seconds=1.0, completion_status=None
            )
        )
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
# restore_subagent_state / _deserialize_message
# =========================================================================


class _FakeCheckpointer:
    def __init__(self, *, fail: bool = False) -> None:
        self.puts: list[tuple[object, object]] = []
        self._fail = fail

    async def aput(
        self, config: object, checkpoint: object, metadata: object, versions: object
    ) -> None:
        if self._fail:
            raise RuntimeError("aput exploded")
        self.puts.append((config, checkpoint))


class TestRestoreState:
    @pytest.mark.asyncio
    async def test_variables_restore_the_runtime_context(self) -> None:
        agent = _FakeAgent()
        await restore_subagent_state(  # type: ignore[arg-type]
            agent, {"messages": [], "variables": {"session_id": "s2"}}
        )

        assert agent._last_context == {"session_id": "s2"}

    @pytest.mark.asyncio
    async def test_empty_variables_leave_context_untouched(self) -> None:
        agent = _FakeAgent(last_context={"session_id": "keep"})
        await restore_subagent_state(agent, {"messages": [], "variables": {}})  # type: ignore[arg-type]

        assert agent._last_context == {"session_id": "keep"}

    @pytest.mark.asyncio
    async def test_messages_are_written_to_the_checkpointer(self) -> None:
        checkpointer = _FakeCheckpointer()
        agent = _FakeAgent()
        agent.checkpointer = checkpointer  # type: ignore[attr-defined]

        await restore_subagent_state(  # type: ignore[arg-type]
            agent,
            {
                "messages": [
                    {"type": "human", "content": "hi"},
                    {"type": "ai", "content": "yo"},
                ]
            },
        )

        assert len(checkpointer.puts) == 1
        _, checkpoint = checkpointer.puts[0]
        assert len(checkpoint["channel_values"]["messages"]) == 2  # type: ignore[index]

    @pytest.mark.asyncio
    async def test_missing_checkpointer_skips_message_restoration(self) -> None:
        agent = _FakeAgent()
        agent.checkpointer = None  # type: ignore[attr-defined]

        # Must not raise even though messages exist.
        await restore_subagent_state(agent, {"messages": [{"type": "human", "content": "x"}]})  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_checkpointer_write_failure_is_swallowed(self) -> None:
        agent = _FakeAgent()
        agent.checkpointer = _FakeCheckpointer(fail=True)  # type: ignore[attr-defined]

        await restore_subagent_state(agent, {"messages": [{"type": "human", "content": "x"}]})  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_undeserializable_messages_short_circuit_to_zero_writes(self) -> None:
        checkpointer = _FakeCheckpointer()
        agent = _FakeAgent()
        agent.checkpointer = checkpointer  # type: ignore[attr-defined]

        await restore_subagent_state(agent, {"messages": [{"type": "bogus"}]})  # type: ignore[arg-type]

        assert checkpointer.puts == []


class TestDeserializeMessage:
    def test_each_supported_message_type_round_trips(self) -> None:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

        from myrm_agent_harness.agent.sub_agents.checkpoint.state_extractor import (
            _deserialize_message,
        )

        cases: list[tuple[dict[str, object], type[object]]] = [
            ({"type": "human", "content": "h"}, HumanMessage),
            ({"type": "ai", "content": "a"}, AIMessage),
            ({"type": "system", "content": "s"}, SystemMessage),
            ({"type": "tool", "content": "t", "tool_call_id": "c1"}, ToolMessage),
        ]
        for payload, expected in cases:
            restored = _deserialize_message(payload)
            assert isinstance(restored, expected), payload

    def test_unknown_type_returns_none(self) -> None:
        from myrm_agent_harness.agent.sub_agents.checkpoint.state_extractor import (
            _deserialize_message,
        )

        assert _deserialize_message({"type": "alien", "content": "?"}) is None

    def test_deserialization_failure_returns_none(self) -> None:
        from myrm_agent_harness.agent.sub_agents.checkpoint.state_extractor import (
            _deserialize_message,
        )

        # tool_calls must be a list; a bare string makes AIMessage raise.
        assert _deserialize_message({"type": "ai", "content": "x", "tool_calls": "bad"}) is None

