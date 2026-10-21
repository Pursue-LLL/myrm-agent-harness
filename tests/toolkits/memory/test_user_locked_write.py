"""Writing near a user-locked memory must never overwrite it.

The deterministic merge runs before the LLM judge, so this is the last line of
defence for a fact the user explicitly pinned.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument, VectorSearchResult
from myrm_agent_harness.toolkits.memory.strategies.deduplicator import SmartDeduplicator
from myrm_agent_harness.toolkits.memory.types import SemanticMemory

LOCKED = "项目必须使用 PostgreSQL"


def _store_holding_locked_fact() -> AsyncMock:
    now = datetime.now(UTC)
    vector = AsyncMock()
    vector.search = AsyncMock(
        return_value=[
            VectorSearchResult(
                document=VectorDocument(
                    id="mem_locked",
                    content=LOCKED,
                    vector=[0.5] * 768,
                    created_at=now,
                    updated_at=now,
                    metadata={
                        "created_at": now.isoformat(),
                        "updated_at": now.isoformat(),
                        "access_count": 1,
                        "importance": 0.5,
                        "confidence": 1.0,
                        "merge_count": 0,
                        "merge_history": "",
                        "pinned": True,
                        "language": "zh",
                    },
                ),
                score=0.85,
            )
        ]
    )
    vector.get = AsyncMock(return_value=[])
    return vector


def _embedding() -> AsyncMock:
    embedder = AsyncMock()
    embedder.embed = AsyncMock(return_value=[0.1] * 768)
    embedder.embed_batch = AsyncMock(return_value=[[0.1] * 768])
    return embedder


@pytest.mark.asyncio
async def test_user_locked_fact_survives_a_competing_write() -> None:
    incoming = SemanticMemory(content="项目改用 MySQL", confidence=0.9)

    kept = await SmartDeduplicator(AsyncMock()).deduplicate_batch(
        [incoming],
        vector=_store_holding_locked_fact(),
        embedding=_embedding(),
        memory_config=MemoryConfig(embedding_model="test-model"),
        cache=None,
    )

    assert [m.content for m in kept] == [incoming.content]
