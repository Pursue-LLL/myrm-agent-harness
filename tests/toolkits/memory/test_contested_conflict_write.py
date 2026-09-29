"""A conflicting write must leave the new statement on record as contested.

The retention pass spares a memory carrying this flag until a human settles the
dispute. Without it, the weaker side of a reversed decision can be culled while
the user has not chosen, and the agent may raise the rejected option again with
no trace that it was ever weighed.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument, VectorSearchResult
from myrm_agent_harness.toolkits.memory.strategies.deduplicator import SmartDeduplicator
from myrm_agent_harness.toolkits.memory.types import SemanticMemory

REJECTED = "项目缓存使用 Redis"
CHOSEN = "项目缓存改用 Memcached"


def _store_holding_rejected_choice() -> AsyncMock:
    """Vector store that already holds the option the user turned down."""
    now = datetime.now(UTC)
    vector = AsyncMock()
    vector.search = AsyncMock(
        return_value=[
            VectorSearchResult(
                document=VectorDocument(
                    id="mem_redis",
                    content=REJECTED,
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
                        "language": "zh",
                    },
                ),
                score=0.80,
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


async def _write_reversed_choice() -> list[SemanticMemory]:
    chosen = SemanticMemory(content=CHOSEN, confidence=0.9)
    kept = await SmartDeduplicator(AsyncMock()).deduplicate_batch(
        [chosen],
        vector=_store_holding_rejected_choice(),
        embedding=_embedding(),
        memory_config=MemoryConfig(embedding_model="test-model"),
        cache=None,
    )
    return list(kept)


@pytest.mark.asyncio
async def test_reversed_decision_is_kept_rather_than_merged_away() -> None:
    kept = await _write_reversed_choice()

    assert [m.content for m in kept] == [CHOSEN]


@pytest.mark.asyncio
async def test_reversed_decision_is_marked_contested_and_decayed() -> None:
    kept = await _write_reversed_choice()

    assert kept[0].metadata["conflict_status"] == "conflicted"
    assert kept[0].confidence == 0.35


@pytest.mark.asyncio
async def test_agreeing_statement_is_not_marked_contested() -> None:
    """A restatement of the same choice must not raise a governance flag."""
    vector = AsyncMock()
    now = datetime.now(UTC)
    vector.search = AsyncMock(
        return_value=[
            VectorSearchResult(
                document=VectorDocument(
                    id="mem_redis",
                    content=CHOSEN,
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
                        "language": "zh",
                    },
                ),
                score=0.99,
            )
        ]
    )
    vector.get = AsyncMock(return_value=[])

    restated = SemanticMemory(content=CHOSEN, confidence=0.9)
    await SmartDeduplicator(AsyncMock()).deduplicate_batch(
        [restated],
        vector=vector,
        embedding=_embedding(),
        memory_config=MemoryConfig(embedding_model="test-model"),
        cache=None,
    )

    assert "conflict_status" not in restated.metadata


@pytest.mark.asyncio
async def test_stored_side_of_a_conflict_is_persisted_as_contested() -> None:
    """The rejected record is the one that decays, so its flag must reach the store.

    The stored memory is rebuilt from the search hit on every call, so flagging
    the in-memory copy proves nothing: only a write-back protects the older record
    from the retention pass.
    """
    now = datetime.now(UTC)
    stored = VectorDocument(
        id="mem_redis",
        content="项目缓存使用 Redis，因为性能好",
        vector=[0.5] * 768,
        created_at=now,
        updated_at=now,
        metadata={"created_at": now.isoformat(), "updated_at": now.isoformat(), "language": "zh"},
    )
    vector = AsyncMock()
    vector.search = AsyncMock(
        return_value=[VectorSearchResult(document=stored, score=0.83)],
    )
    vector.upsert = AsyncMock(return_value=[stored.id])

    incoming = SemanticMemory(content="项目缓存不再使用 Redis，改用 Memcached，因为运维更熟", confidence=0.9)
    kept = await SmartDeduplicator(AsyncMock()).deduplicate_batch(
        [incoming],
        vector=vector,
        embedding=_embedding(),
        memory_config=MemoryConfig(embedding_model="test-model"),
        cache=None,
    )

    assert kept[0].metadata.get("conflict_status") == "conflicted"
    vector.upsert.assert_awaited_once()
    collection, written = vector.upsert.await_args.args
    assert written[0].id == stored.id
    assert written[0].content == stored.content, "the rejected record keeps its content"
    assert written[0].metadata["conflict_status"] == "conflicted"
    assert isinstance(collection, str) and collection
