"""Unit tests for memory_citations module.

Covers cited_memory_ref, _bounded_text, and emit_cited_memory_ids.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.memory.memory_citations import (
    MAX_CITATION_CONTENT_CHARS,
    cited_memory_ref,
    emit_cited_memory_ids,
)
from myrm_agent_harness.toolkits.memory.types import MemoryType


@dataclass
class FakeScope:
    primary_namespace: str = "default"
    namespaces: list[str] = field(default_factory=lambda: ["default", "shared"])


@dataclass
class FakeMemory:
    id: str = "mem-001"
    content: str = "Test memory content"
    created_at: datetime | None = None
    source_chat_id: str | None = None
    source_message_id: str | None = None
    scope: FakeScope | None = None


class TestCitedMemoryRef:
    """Tests for cited_memory_ref function."""

    def test_basic_fields(self) -> None:
        memory = FakeMemory(scope=FakeScope())
        ref = cited_memory_ref(memory, MemoryType.EPISODIC, 0.85)

        assert ref["id"] == "mem-001"
        assert ref["memory_type"] == "episodic"
        assert ref["content"] == "Test memory content"
        assert ref["score"] == 0.85
        assert ref["primary_namespace"] == "default"
        assert ref["namespaces"] == ["default", "shared"]

    def test_score_rounding(self) -> None:
        memory = FakeMemory(scope=FakeScope())
        ref = cited_memory_ref(memory, MemoryType.EPISODIC, 0.123456789)
        assert ref["score"] == 0.1235

    def test_optional_chat_id(self) -> None:
        memory = FakeMemory(source_chat_id="chat-123", scope=FakeScope())
        ref = cited_memory_ref(memory, MemoryType.EPISODIC, 0.9)
        assert ref["source_chat_id"] == "chat-123"

    def test_optional_message_id(self) -> None:
        memory = FakeMemory(source_message_id="msg-456", scope=FakeScope())
        ref = cited_memory_ref(memory, MemoryType.EPISODIC, 0.9)
        assert ref["source_message_id"] == "msg-456"

    def test_no_optional_fields_when_empty(self) -> None:
        memory = FakeMemory(scope=FakeScope())
        ref = cited_memory_ref(memory, MemoryType.EPISODIC, 0.9)
        assert "source_chat_id" not in ref
        assert "source_message_id" not in ref

    def test_created_at_iso_format(self) -> None:
        dt = datetime(2026, 1, 15, 10, 30, 0, tzinfo=UTC)
        memory = FakeMemory(created_at=dt, scope=FakeScope())
        ref = cited_memory_ref(memory, MemoryType.EPISODIC, 0.9)
        assert ref["created_at"] == "2026-01-15T10:30:00+00:00"

    def test_no_created_at_when_none(self) -> None:
        memory = FakeMemory(scope=FakeScope())
        ref = cited_memory_ref(memory, MemoryType.EPISODIC, 0.9)
        assert "created_at" not in ref

    def test_no_scope(self) -> None:
        memory = FakeMemory(scope=None)
        ref = cited_memory_ref(memory, MemoryType.EPISODIC, 0.9)
        assert ref["primary_namespace"] == ""
        assert ref["namespaces"] == []


class TestBoundedText:
    """Tests for content truncation in cited_memory_ref."""

    def test_short_content_not_truncated(self) -> None:
        memory = FakeMemory(content="Short", scope=FakeScope())
        ref = cited_memory_ref(memory, MemoryType.EPISODIC, 0.9)
        assert ref["content"] == "Short"

    def test_long_content_truncated(self) -> None:
        long_content = "A" * (MAX_CITATION_CONTENT_CHARS + 100)
        memory = FakeMemory(content=long_content, scope=FakeScope())
        ref = cited_memory_ref(memory, MemoryType.EPISODIC, 0.9)
        assert ref["content"].endswith("...")
        assert len(ref["content"]) == MAX_CITATION_CONTENT_CHARS + 3

    def test_exact_limit_not_truncated(self) -> None:
        exact_content = "A" * MAX_CITATION_CONTENT_CHARS
        memory = FakeMemory(content=exact_content, scope=FakeScope())
        ref = cited_memory_ref(memory, MemoryType.EPISODIC, 0.9)
        assert ref["content"] == exact_content
        assert not ref["content"].endswith("...")

    def test_citation_content_redacts_credentials(self) -> None:
        secret = "sk-proj-abcdefghij1234567890"
        memory = FakeMemory(content=f"Stored key {secret}", scope=FakeScope())
        ref = cited_memory_ref(memory, MemoryType.SEMANTIC, 0.9)
        assert secret not in str(ref["content"])
        assert "Stored key" in str(ref["content"])


class TestEmitCitedMemoryIds:
    """Tests for emit_cited_memory_ids function."""

    @pytest.mark.asyncio
    async def test_emit_calls_sink(self) -> None:
        mock_sink = AsyncMock()
        mock_sink.emit = AsyncMock()

        with (
            patch(
                "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
                return_value=mock_sink,
            ),
            patch(
                "myrm_agent_harness.core.events.types.AgentEventType",
            ) as mock_event_type,
        ):
            mock_event_type.TOOL_END.value = "tool_end"
            await emit_cited_memory_ids(
                ["mem-1"],
                [{"id": "mem-1", "content": "safe"}],
                tool_name="memory_search_tool",
            )

            mock_sink.emit.assert_called_once()
            payload = mock_sink.emit.call_args[0][0]
            assert payload["tool_name"] == "memory_search_tool"
            assert payload["cited_memory_ids"] == ["mem-1"]

    @pytest.mark.asyncio
    async def test_emit_handles_no_sink(self) -> None:
        with patch(
            "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
            return_value=None,
        ):
            await emit_cited_memory_ids(["mem-1"])

    @pytest.mark.asyncio
    async def test_emit_handles_sink_error(self) -> None:
        mock_sink = AsyncMock()
        mock_sink.emit = AsyncMock(side_effect=RuntimeError("sink down"))

        with (
            patch(
                "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
                return_value=mock_sink,
            ),
            patch(
                "myrm_agent_harness.core.events.types.AgentEventType",
            ) as mock_event_type,
        ):
            mock_event_type.TOOL_END.value = "tool_end"
            await emit_cited_memory_ids(["mem-1"])
