"""Checkpoint snapshot primitives — serialization, context sanitation, stat projection.

These cover the contract surfaces that every checkpoint writer depends on:
``serialize_message`` message shapes, ``sanitize_persistable_context`` removing the
non-serializable workspace bind token, and ``project_run_statistics`` payload shape.
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.agent.sub_agents.checkpoint.state_snapshot import (
    project_run_statistics,
    sanitize_persistable_context,
    serialize_message,
)
from myrm_agent_harness.toolkits.code_execution.workspace.storage_root_bind import (
    WORKSPACE_BIND_CTX_KEY,
)


class _Status(Enum):
    COMPLETED = "completed"


@dataclass
class _TokenUsage:
    total_tokens: int = 10

    def to_dict(self) -> dict[str, int]:
        return {"total_tokens": self.total_tokens}


@dataclass
class _RunStats:
    token_usage: _TokenUsage | None = None
    total_duration_seconds: float = 3.5
    completion_status: _Status | None = _Status.COMPLETED


class TestSerializeMessage:
    def test_pydantic_message_uses_model_dump(self) -> None:
        dumped = serialize_message(HumanMessage(content="hello"))

        assert dumped["type"] == "human"
        assert dumped["content"] == "hello"

    def test_object_without_model_dump_falls_back_to_to_json(self) -> None:
        class LegacyMessage:
            def to_json(self) -> dict[str, object]:
                return {"type": "legacy", "content": "x"}

        assert serialize_message(LegacyMessage()) == {"type": "legacy", "content": "x"}

    def test_object_without_any_serializer_is_wrapped_as_unknown(self) -> None:
        assert serialize_message(42) == {"type": "unknown", "content": "42"}


class TestSanitizePersistableContext:
    def test_none_becomes_empty_dict(self) -> None:
        assert sanitize_persistable_context(None) == {}

    def test_workspace_bind_token_is_removed(self) -> None:
        cv: ContextVar[object] = ContextVar("probe", default=None)
        token = cv.set(object())

        sanitized = sanitize_persistable_context(
            {"goal": "demo", WORKSPACE_BIND_CTX_KEY: token}
        )

        assert sanitized == {"goal": "demo"}
        # The result must survive the JSON persistence step that previously failed.
        json.dumps(sanitized)

    def test_original_context_is_not_mutated(self) -> None:
        original = {"goal": "demo"}
        sanitize_persistable_context(original)

        assert original == {"goal": "demo"}

    def test_token_is_genuinely_unserializable(self) -> None:
        """Guards the premise: if Token ever becomes serializable, the strip is dead code."""
        cv: ContextVar[object] = ContextVar("probe2", default=None)
        token = cv.set(object())

        with pytest.raises(TypeError):
            json.dumps({"token": token})


class TestProjectRunStatistics:
    def test_completed_run_projects_payload_and_full_progress(self) -> None:
        stats, progress = project_run_statistics(_RunStats(token_usage=_TokenUsage(200)))

        assert stats["token_usage"] == {"total_tokens": 200}
        assert stats["duration_seconds"] == 3.5
        assert stats["status"] == "completed"
        assert progress == 1.0

    def test_missing_token_usage_projects_empty_dict(self) -> None:
        stats, _ = project_run_statistics(_RunStats(token_usage=None))

        assert stats["token_usage"] == {}

    def test_missing_completion_status_projects_unknown_and_half_progress(self) -> None:
        stats, progress = project_run_statistics(_RunStats(completion_status=None))

        assert stats["status"] == "unknown"
        assert progress == 0.5

    def test_payload_is_json_serializable(self) -> None:
        stats, _ = project_run_statistics(_RunStats())

        json.dumps(stats)


class TestExtractCheckpointStateUsesSanitizer:
    @pytest.mark.asyncio
    async def test_bind_token_is_stripped_from_extracted_context(self) -> None:
        from myrm_agent_harness.agent.sub_agents.checkpoint.state_snapshot import (
            extract_checkpoint_state,
        )

        cv: ContextVar[object] = ContextVar("probe3", default=None)
        state = await extract_checkpoint_state(
            checkpointer=None,
            last_context={"goal": "demo", WORKSPACE_BIND_CTX_KEY: cv.set(object())},
            last_run_stats=None,
            thread_id="t1",
        )

        assert state["context"] == {"goal": "demo"}
        json.dumps(state["context"])

    @pytest.mark.asyncio
    async def test_messages_are_serialized_and_last_tool_detected(self) -> None:
        from unittest.mock import AsyncMock

        from myrm_agent_harness.agent.sub_agents.checkpoint.state_snapshot import (
            extract_checkpoint_state,
        )

        messages = [
            HumanMessage(content="read a file"),
            AIMessage(
                content="",
                tool_calls=[{"name": "file_read_tool", "args": {}, "id": "c1"}],
            ),
        ]
        checkpointer = AsyncMock()
        checkpointer.aget = AsyncMock(
            return_value={"channel_values": {"messages": messages}}
        )

        state = await extract_checkpoint_state(
            checkpointer=checkpointer,
            last_context=None,
            last_run_stats=None,
            thread_id="t1",
        )

        assert len(state["messages"]) == 2
        assert state["last_tool"] == "file_read_tool"

    @pytest.mark.asyncio
    async def test_run_statistics_are_project_into_the_snapshot(self) -> None:
        from myrm_agent_harness.agent.sub_agents.checkpoint.state_snapshot import (
            extract_checkpoint_state,
        )

        state = await extract_checkpoint_state(
            checkpointer=None,
            last_context=None,
            last_run_stats=_RunStats(token_usage=_TokenUsage(77)),
            thread_id="t1",
        )

        assert state["stats"]["token_usage"] == {"total_tokens": 77}
        assert state["progress"] == 1.0
