"""Tests for MemoryPreCompactService query and formatting."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from langchain_core.messages import HumanMessage

from myrm_agent_harness.agent.context_management.pre_compact_service import MemoryPreCompactService
from myrm_agent_harness.toolkits.memory.types import MemorySearchResult, MemoryType, SemanticMemory


class _FakeManager:
    def __init__(self, results: list[MemorySearchResult]) -> None:
        self._results = results

    async def search(self, query: str, *, limit: int = 10, use_rrf: bool = True):
        assert query
        assert limit >= 1
        return self._results


@pytest.mark.asyncio
async def test_build_injection_formats_human_message() -> None:
    memory = SemanticMemory(
        id="mem-auth-rule",
        content="Never modify the auth module during refactors.",
        created_at=datetime.now(UTC),
    )
    manager = _FakeManager(
        [
            MemorySearchResult(
                memory=memory,
                score=0.91,
                memory_type=MemoryType.SEMANTIC,
            )
        ]
    )
    service = MemoryPreCompactService(manager)

    injection = await service.build_injection(
        messages=[HumanMessage(content="continue refactor")],
        chat_id="chat-1",
        user_id="user-1",
        compaction_tier="compress",
        token_pressure_ratio=0.8,
        user_goal_hint="refactor payment module",
    )

    assert injection is not None
    assert injection.recalled_ids == ("mem-auth-rule",)
    assert "mem-auth-rule" in str(injection.message.content)
    assert "Never modify the auth module" in str(injection.message.content)


@pytest.mark.asyncio
async def test_build_injection_includes_archive_checkpoint_milestone() -> None:
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock, MagicMock

    from myrm_agent_harness.agent.context_management.archive_checkpoint.types import (
        ARCHIVE_CHECKPOINT_EVENT_TYPE,
    )
    from myrm_agent_harness.toolkits.vector.base import VectorDocument

    doc = VectorDocument(
        id="mem-archive-1",
        content="Archive checkpoint (tool=grep_tool, path=.context/chat/compacted/out.txt):\nQ3 -12%",
        metadata={
            "memory_type": MemoryType.EPISODIC.value,
            "event_type": ARCHIVE_CHECKPOINT_EVENT_TYPE,
            "source_chat_id": "chat-1",
            "related_entities": ["grep_tool", ".context/chat/compacted/out.txt"],
        },
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    class _ScrollManager:
        has_vector = True
        _vector = AsyncMock()
        _config = MagicMock(episodic_collection="episodic")

        def __init__(self) -> None:
            self._vector.scroll.return_value = ([doc], None)

        async def search(self, query: str, *, limit: int = 10, use_rrf: bool = True):
            _ = query, limit, use_rrf
            return []

    service = MemoryPreCompactService(_ScrollManager())
    injection = await service.build_injection(
        messages=[HumanMessage(content="continue analysis")],
        chat_id="chat-1",
        user_id="user-1",
        compaction_tier="compress",
        token_pressure_ratio=0.9,
        user_goal_hint="",
    )

    assert injection is not None
    assert "mem-archive-1" in str(injection.message.content)
    assert "Recent Archive Checkpoints" in str(injection.message.content)
    assert "Q3 -12%" in str(injection.message.content)
