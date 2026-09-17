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


@pytest.mark.asyncio
async def test_debounce_starvation_prevention(tmp_path: Path) -> None:
    """Continuous writes faster than debounce_interval must still flush once max_debounce_interval is reached."""
    db_file = tmp_path / "mirror_starve.db"
    # Normal debounce 100ms, but hard max timeout 200ms
    engine = HotColdMirrorEngine(
        db_file,
        debounce_interval=0.1,
        max_debounce_interval=0.2,
    )
    await engine.initialize()

    # Rapid writes: each write arrives at ~60ms intervals (faster than 100ms debounce)
    # Without hard timeout, it would keep postponing indefinitely.
    for i in range(5):
        mem = SemanticMemory(
            id=f"mem-starve-{i}",
            content=f"Rapid log {i}",
            domain=MemoryDomain.TASK,
            domain_category=DomainCategory.TRAJECTORIES.value,
        )
        engine.put_hot(mem)
        await asyncio.sleep(0.06)

    # By step 4 (4 * 60ms = 240ms > 200ms max_debounce_interval), a flush should have been triggered!
    cold_count = await engine.count_cold(domain=MemoryDomain.TASK)
    assert cold_count > 0, "Hard debounce timeout must flush records despite continuous incoming writes"

    await engine.close()


@pytest.mark.asyncio
async def test_flush_failure_rollback_and_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When SQLite executemany fails, dirty records must be rolled back to _pending_sync for retry."""
    db_file = tmp_path / "mirror_retry.db"
    engine = HotColdMirrorEngine(db_file, debounce_interval=1.0)
    await engine.initialize()

    mem = SemanticMemory(
        id="mem-fail-retry",
        content="Important lesson that must not be lost",
        domain=MemoryDomain.TASK,
        domain_category=DomainCategory.TRAPS.value,
    )
    engine.put_hot(mem)

    # Simulate SQLite connection failure during executemany
    conn = await engine._ensure_connection()
    original_executemany = conn.executemany

    async def mock_executemany_fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("Disk full / SQLite locked simulation")

    monkeypatch.setattr(conn, "executemany", mock_executemany_fail)

    with pytest.raises(RuntimeError, match="Disk full / SQLite locked simulation"):
        await engine.flush()

    # Verify memory item was safely rolled back to pending sync
    assert "mem-fail-retry" in engine._pending_sync, "Uncommitted record must be rolled back into pending sync"
    assert engine._first_pending_time is not None, "Pending timer must be restored on flush failure"

    # Restore normal executemany and retry flush
    monkeypatch.setattr(conn, "executemany", original_executemany)
    flushed_count = await engine.flush()
    assert flushed_count == 1
    assert "mem-fail-retry" not in engine._pending_sync

    # Cold store now has the record
    records = await engine.query_cold(domain=MemoryDomain.TASK)
    assert len(records) == 1
    assert records[0].id == "mem-fail-retry"
    assert records[0].content == "Important lesson that must not be lost"

    await engine.close()

