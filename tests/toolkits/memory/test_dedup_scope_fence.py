"""Scope-fence tests for memory write/dedup security (P0).

Covers the write-path fence in ``MemoryWriter``, namespace-scoped dedup
candidates, cross-scope merge downgrade, namespace-scoped hash cache, and
the fallback maintenance dedup path — the same vulnerability class as
gbrain #3809 (dedup-resolved writes escaping the caller's scope).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.memory._internal.maintenance import dedup_semantics
from myrm_agent_harness.toolkits.memory._internal.storage import MemoryError
from myrm_agent_harness.toolkits.memory._internal.storage_converters import _user_filter
from myrm_agent_harness.toolkits.memory._internal.write_service import MemoryWriter
from myrm_agent_harness.toolkits.memory.strategies.deduplicator import (
    DeduplicationDecision,
    SmartDeduplicator,
)
from myrm_agent_harness.toolkits.memory.types import MemoryScope, SemanticMemory
from myrm_agent_harness.toolkits.vector.base import SearchResult, VectorDocument


def _semantic(content: str, *, ns: list[str], embedding: list[float] | None = None) -> SemanticMemory:
    return SemanticMemory(
        content=content,
        scope=MemoryScope(namespaces=ns),
        embedding=embedding or [0.5, 0.5],
    )


def _config() -> MagicMock:
    config = MagicMock()
    config.semantic_collection = "semantic"
    config.episodic_collection = "episodic"
    return config


def _new_deduplicator() -> SmartDeduplicator:
    return SmartDeduplicator(MagicMock(), persist_hash_cache=False)


class ScopeAwareVector:
    """Minimal vector store honoring the ``primary_namespace`` filter key."""

    def __init__(self) -> None:
        self.docs: dict[str, VectorDocument] = {}

    async def search(self, collection, query_vector, *, limit=10, filters=None, score_threshold=None):
        allow = set((filters or {}).get("primary_namespace", []))
        hits = [d for d in self.docs.values() if d.metadata.get("primary_namespace") in allow]
        if not hits:
            return []
        return [SearchResult(document=hits[0], score=0.97)]

    async def get(self, collection, ids):
        return [self.docs[i] for i in ids if i in self.docs]

    async def upsert(self, collection, documents):
        for doc in documents:
            self.docs[doc.id] = doc


# ── R2: dedup candidate fence ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_dedup_search_filters_by_memory_namespaces() -> None:
    """Dedup candidates must be restricted to the memory's own namespaces."""
    dedup = _new_deduplicator()
    vector = AsyncMock()
    vector.search = AsyncMock(return_value=[])
    mem = _semantic("User prefers Python", ns=["agent:A"])

    out = await dedup.deduplicate_batch([mem], vector, AsyncMock(), _config(), None)

    assert len(out) == 1
    _, kwargs = vector.search.call_args
    assert kwargs["filters"] == _user_filter(namespaces=["agent:A"])


@pytest.mark.asyncio
async def test_dedup_does_not_suppress_other_agents_memory() -> None:
    """Agent A memory must not be suppressed by agent B's similar record."""
    store = ScopeAwareVector()
    await store.upsert(
        "semantic",
        [
            VectorDocument(
                id="mem-b",
                content="User prefers Python over Rust",
                metadata={
                    "primary_namespace": "agent:B",
                    "namespaces": ["global", "agent:B"],
                },
            )
        ],
    )
    dedup = _new_deduplicator()
    mem_a = _semantic("User prefers Python over Rust", ns=["agent:A"])

    out = await dedup.deduplicate_batch([mem_a], store, AsyncMock(), _config(), None)

    assert len(out) == 1  # NEW — created in agent A's own scope


@pytest.mark.asyncio
async def test_dedup_cross_agent_shared_global_does_not_leak_candidates() -> None:
    """A foreign agent's record that merely shares the ``global`` broadcast
    namespace must never become a dedup candidate (P0 cross-agent fence).

    Production records carry ``namespaces`` including ``global``, so a loose
    intersect on that list would let agent B match agent A's memory. The
    filter keys on ``primary_namespace`` exactly, so the match fails and the
    new memory is kept instead of being suppressed or merged into A.
    """
    store = ScopeAwareVector()
    await store.upsert(
        "semantic",
        [
            VectorDocument(
                id="mem-a",
                content="User prefers Python over Rust",
                metadata={
                    "primary_namespace": "agent:A",
                    "namespaces": ["global", "agent:A"],
                },
            )
        ],
    )
    dedup = _new_deduplicator()
    mem_b = _semantic("User prefers Python over Rust", ns=["global", "agent:B"])

    out = await dedup.deduplicate_batch([mem_b], store, AsyncMock(), _config(), None)

    assert len(out) == 1  # kept as NEW — agent A's memory is invisible to agent B


@pytest.mark.asyncio
async def test_dedup_global_memory_does_not_restrict_candidates() -> None:
    """A global (namespace-less) memory still dedups against the whole collection."""
    dedup = _new_deduplicator()
    vector = AsyncMock()
    vector.search = AsyncMock(return_value=[])
    mem = _semantic("Global fact", ns=[])

    out = await dedup.deduplicate_batch([mem], vector, AsyncMock(), _config(), None)

    assert len(out) == 1
    _, kwargs = vector.search.call_args
    assert kwargs["filters"] == _user_filter()
    assert "primary_namespace" not in kwargs["filters"]


@pytest.mark.asyncio
async def test_dedup_episodic_filters_by_namespace() -> None:
    """Episodic dedup candidates are scoped to the memory's namespaces too."""
    from myrm_agent_harness.toolkits.memory.types import EpisodicMemory

    dedup = _new_deduplicator()
    vector = AsyncMock()
    vector.search = AsyncMock(return_value=[])
    mem = EpisodicMemory(
        content="User clicked export",
        event_type="action",
        scope=MemoryScope(namespaces=["agent:A"]),
        embedding=[0.5, 0.5],
    )

    out = await dedup.deduplicate_batch([mem], vector, AsyncMock(), _config(), None)

    assert len(out) == 1
    _, kwargs = vector.search.call_args
    assert kwargs["filters"] == _user_filter(namespaces=["agent:A"])


# ── R3: merge fence ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_update_downgrades_cross_scope_target_to_new() -> None:
    """Merging into another agent's memory must downgrade to NEW."""
    dedup = _new_deduplicator()
    vector = AsyncMock()
    vector.get = AsyncMock(
        return_value=[
            VectorDocument(
                id="mem-b",
                content="old",
                metadata={
                    "primary_namespace": "agent:B",
                    "namespaces": ["global", "agent:B"],
                },
            )
        ]
    )
    mem = _semantic("User prefers Python", ns=["agent:A"])

    result = await dedup._apply_update(
        mem,
        "mem-b",
        "merged content",
        DeduplicationDecision.UPDATE_MERGE,
        vector,
        _config(),
    )

    assert result is mem  # downgraded to NEW (create original instead of polluting B)


@pytest.mark.asyncio
async def test_apply_update_allows_same_scope_merge() -> None:
    """Same-scope merge still works as before."""
    dedup = _new_deduplicator()
    vector = AsyncMock()
    vector.get = AsyncMock(
        return_value=[
            VectorDocument(
                id="mem-a",
                content="old",
                metadata={
                    "primary_namespace": "agent:A",
                    "namespaces": ["global", "agent:A"],
                },
            )
        ]
    )
    mem = _semantic("User prefers Python", ns=["agent:A"])

    result = await dedup._apply_update(
        mem,
        "mem-a",
        "merged content",
        DeduplicationDecision.UPDATE_MERGE,
        vector,
        _config(),
    )

    assert result is not mem
    assert result.content == "merged content"


# ── R4: namespace-scoped hash cache ───────────────────────────────────


@pytest.mark.asyncio
async def test_hash_cache_does_not_suppress_across_scopes() -> None:
    """Same content in different scopes must both be persisted."""
    dedup = _new_deduplicator()
    vector = AsyncMock()
    vector.search = AsyncMock(return_value=[])
    config = _config()

    out1 = await dedup.deduplicate_batch([_semantic("Same fact", ns=["agent:A"])], vector, AsyncMock(), config, None)
    out2 = await dedup.deduplicate_batch([_semantic("Same fact", ns=["agent:B"])], vector, AsyncMock(), config, None)

    assert len(out1) == 1
    assert len(out2) == 1  # not suppressed by agent A's cache entry


@pytest.mark.asyncio
async def test_hash_cache_still_suppresses_same_scope_duplicate() -> None:
    """Same content in the same scope is still hash-deduplicated."""
    dedup = _new_deduplicator()
    vector = AsyncMock()
    vector.search = AsyncMock(return_value=[])
    config = _config()

    await dedup.deduplicate_batch([_semantic("Same fact", ns=["agent:A"])], vector, AsyncMock(), config, None)
    out2 = await dedup.deduplicate_batch([_semantic("Same fact", ns=["agent:A"])], vector, AsyncMock(), config, None)

    assert len(out2) == 0  # same-scope duplicate suppressed


def test_hash_cache_load_drops_legacy_unscooped_keys() -> None:
    """Pre-fix cache entries without a namespace prefix must be discarded."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = str(Path(tmp_dir) / "hash_cache.json")
        Path(path).write_text(json.dumps({"hashes": ["legacy-hash-no-ns"]}))
        dedup = SmartDeduplicator(MagicMock(), persist_hash_cache=True, hash_cache_path=path)
        assert dedup._hash_cache == {}


# ── R1: write-path fence ──────────────────────────────────────────────


def _writer(namespaces: list[str], *, scope_namespaces: list[str] | None = None) -> MemoryWriter:
    async def _noop(memory):
        return memory

    async def _noop_batch(memories):
        return memories

    config = MagicMock()
    config.security_scan_enabled = False
    return MemoryWriter(
        config=config,
        scope=MemoryScope(namespaces=(scope_namespaces if scope_namespaces is not None else list(namespaces))),
        namespaces=list(namespaces),
        approval_required=False,
        bind_scope_func=lambda m: m,
        submit_pending_func=_noop,
        store_semantic_func=_noop,
        store_episodic_func=_noop,
        store_procedural_func=_noop,
        store_semantics_batch_func=_noop_batch,
        store_episodics_batch_func=_noop_batch,
        store_procedurals_batch_func=_noop_batch,
        store_conversations_batch_func=_noop_batch,
        deduplicate_semantic_batch_func=_noop_batch,
        deduplicate_episodic_batch_func=_noop_batch,
    )


@pytest.mark.asyncio
async def test_store_rejects_out_of_scope_namespace() -> None:
    """Writes targeting another agent's namespace must fail loudly."""
    writer = _writer(namespaces=["agent:A"])
    with pytest.raises(MemoryError):
        await writer.store(_semantic("fact", ns=["agent:B"]))


@pytest.mark.asyncio
async def test_store_accepts_in_scope_namespace() -> None:
    writer = _writer(namespaces=["agent:A"])
    mem = _semantic("fact", ns=["agent:A"])
    assert await writer.store(mem) is mem


@pytest.mark.asyncio
async def test_store_accepts_shared_namespace_from_read_scope() -> None:
    writer = _writer(namespaces=["agent:A", "shared:home"])
    mem = _semantic("fact", ns=["shared:home"])
    assert await writer.store(mem) is mem


@pytest.mark.asyncio
async def test_store_batch_rejects_out_of_scope_namespace() -> None:
    writer = _writer(namespaces=["agent:A"])
    with pytest.raises(MemoryError):
        await writer.store_batch([_semantic("fact", ns=["agent:B"])])


@pytest.mark.asyncio
async def test_store_rejects_read_only_non_shared_namespace() -> None:
    """Read-only namespaces outside the narrowed write scope must be rejected."""
    writer = _writer(
        namespaces=["agent:A", "channel:c1", "task:t1"],
        scope_namespaces=["task:t1"],
    )
    with pytest.raises(MemoryError):
        await writer.store(_semantic("fact", ns=["agent:A"]))


@pytest.mark.asyncio
async def test_store_accepts_write_scope_target() -> None:
    """The narrowed write-policy target remains writable."""
    writer = _writer(
        namespaces=["agent:A", "channel:c1", "task:t1"],
        scope_namespaces=["task:t1"],
    )
    mem = _semantic("fact", ns=["task:t1"])
    assert await writer.store(mem) is mem


@pytest.mark.asyncio
async def test_store_accepts_global_shared_write_under_narrowed_policy() -> None:
    """write_target='shared' falling back to the global namespace stays writable."""
    writer = _writer(
        namespaces=["global", "task:t1"],
        scope_namespaces=["task:t1"],
    )
    mem = _semantic("fact", ns=["global"])
    assert await writer.store(mem) is mem


# ── R5: fallback maintenance dedup ────────────────────────────────────


@pytest.mark.asyncio
async def test_maintenance_dedup_filters_by_namespace() -> None:
    vector = AsyncMock()
    vector.search = AsyncMock(return_value=[])
    mem = _semantic("fact", ns=["agent:A"])

    out = await dedup_semantics([mem], vector, AsyncMock(), _config(), None)

    assert len(out) == 1
    _, kwargs = vector.search.call_args
    assert kwargs["filters"] == _user_filter(namespaces=["agent:A"])


# ── R7: forgetting stays inside namespaces ────────────────────────────


@pytest.mark.asyncio
async def test_run_forgetting_filters_by_namespaces() -> None:
    """Vector forgetting must not delete memories outside the caller's scopes."""
    from myrm_agent_harness.toolkits.memory._internal.maintenance import run_forgetting
    from myrm_agent_harness.toolkits.memory.strategies.forgetting import (
        ForgettingConfig,
    )

    config = _config()
    config.forgetting = ForgettingConfig()
    vector = AsyncMock()
    vector.scroll = AsyncMock(return_value=([], None))

    result = await run_forgetting(vector, config, None, None, namespaces=["agent:A"])

    assert result.forgotten_count == 0
    _, kwargs = vector.scroll.call_args
    assert kwargs["filters"] == _user_filter(namespaces=["agent:A"])


@pytest.mark.asyncio
async def test_forgetting_relation_counts_stay_inside_namespaces() -> None:
    """relation_count neighbors must be counted within the caller's scopes only."""
    from myrm_agent_harness.toolkits.memory._internal.maintenance import (
        _estimate_relation_counts,
    )

    vector = AsyncMock()
    vector.search = AsyncMock(return_value=[])
    mem = _semantic("fact", ns=["agent:A"])

    await _estimate_relation_counts(
        [mem],
        "semantic",
        vector,
        namespaces=["agent:A"],
    )

    _, kwargs = vector.search.call_args
    assert kwargs["filters"] == _user_filter(namespaces=["agent:A"])
