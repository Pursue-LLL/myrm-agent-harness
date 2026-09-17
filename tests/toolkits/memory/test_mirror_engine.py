"""Tests for HotColdMirrorEngine dual-tier memory cache and single-direction sync."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.domain_types import DomainCategory, MemoryDomain
from myrm_agent_harness.toolkits.memory.mirror import HotColdMirrorEngine
from myrm_agent_harness.toolkits.memory.types import SemanticMemory


@pytest.mark.asyncio
async def test_hot_cache_instant_read_write(tmp_path: Path) -> None:
    db_file = tmp_path / "mirror.db"
    engine = HotColdMirrorEngine(db_file, debounce_interval=0.1)
    await engine.initialize()

    mem = SemanticMemory(
        id="mem-h1",
        content="User likes dark mode and fast terminals.",
        summary_l0="Dark mode preference",
        overview_l1="Prefers dark mode in all environments.",
        domain=MemoryDomain.USER,
        domain_category=DomainCategory.PREFERENCES.value,
    )
    engine.put_hot(mem)

    # 1. Instant hot lookup
    cached = engine.get_hot("mem-h1")
    assert cached is not None
    assert cached.content == "User likes dark mode and fast terminals."
    assert engine.hot_count == 1

    # 2. Wait for debounce flush to cold SQLite
    await asyncio.sleep(0.15)
    cold_records = await engine.query_cold(domain=MemoryDomain.USER)
    assert len(cold_records) == 1
    assert cold_records[0].id == "mem-h1"
    assert cold_records[0].summary_l0 == "Dark mode preference"
    assert cold_records[0].overview_l1 == "Prefers dark mode in all environments."

    await engine.close()


@pytest.mark.asyncio
async def test_cold_to_hot_strong_isolation(tmp_path: Path) -> None:
    db_file = tmp_path / "mirror_iso.db"
    engine = HotColdMirrorEngine(db_file, debounce_interval=0.05)
    await engine.initialize()

    mem1 = SemanticMemory(
        id="mem-hot-1",
        content="Active assistant soul guideline.",
        domain=MemoryDomain.ASSISTANT,
        domain_category=DomainCategory.SOUL.value,
    )
    engine.put_hot(mem1)
    await engine.flush()

    # Hot cache has 1 item
    assert engine.hot_count == 1

    # Directly insert an offline/cold record into the cold DB
    conn = await engine._ensure_connection()
    await conn.execute(
        """
        INSERT INTO cold_memory_mirror (
            id, user_id, domain, domain_category, memory_type,
            summary_l0, overview_l1, content, metadata_json,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "cold-only-id",
            "default",
            MemoryDomain.TASK.value,
            DomainCategory.TRAPS.value,
            "semantic",
            "Trap L0",
            "Trap L1",
            "Offline discovered trap",
            "{}",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        ),
    )
    await conn.commit()

    # Query cold store
    cold_items = await engine.query_cold(domain=MemoryDomain.TASK)
    assert len(cold_items) == 1
    assert cold_items[0].id == "cold-only-id"

    # CRITICAL INVARIANT: Hot cache must NEVER be polluted by cold query or cold records!
    assert engine.get_hot("cold-only-id") is None
    assert engine.hot_count == 1
    assert [m.id for m in engine.list_hot()] == ["mem-hot-1"]

    await engine.close()


@pytest.mark.asyncio
async def test_hot_cache_capacity_eviction(tmp_path: Path) -> None:
    db_file = tmp_path / "mirror_evict.db"
    engine = HotColdMirrorEngine(db_file, max_hot_entries=3, debounce_interval=0.05)
    await engine.initialize()

    for i in range(4):
        mem = SemanticMemory(
            id=f"mem-{i}",
            content=f"Content {i}",
            domain=MemoryDomain.USER,
            domain_category=DomainCategory.PROFILE.value,
        )
        engine.put_hot(mem)

    # Oldest (mem-0) should be evicted from hot cache, leaving 3 items
    assert engine.hot_count == 3
    assert engine.get_hot("mem-0") is None
    assert engine.get_hot("mem-3") is not None

    # But after flush, all 4 are persisted in cold storage!
    await engine.flush()
    cold_count = await engine.count_cold(domain=MemoryDomain.USER)
    assert cold_count == 4

    await engine.close()
