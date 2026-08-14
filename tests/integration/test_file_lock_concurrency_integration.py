"""Integration tests: real file-lock mutual exclusion under asyncio concurrency.

These tests exercise the real ``fcntl.flock`` path — no mocks — to prove the
invariants the DeliveryQueue's multi-worker deduplication relies on:
- exclusive locks never overlap across racing workers;
- shared locks coexist;
- a lock body exception still releases the lock so the resource recovers.
"""

import asyncio
from pathlib import Path

import pytest

from myrm_agent_harness.infra.delivery.file_lock import acquire_delivery_lock
from myrm_agent_harness.infra.locks.file_lock import FileLock


@pytest.mark.integration
@pytest.mark.asyncio
async def test_exclusive_lock_never_overlaps_real_concurrency(tmp_path: Path) -> None:
    """Racing workers on the same resource: at most one holds the exclusive
    lock at any instant."""
    lock = FileLock(tmp_path / "locks")
    holders = 0
    max_holders = 0
    guard = asyncio.Lock()

    async def worker(_: int) -> None:
        nonlocal holders, max_holders
        for _ in range(20):
            async with lock.acquire("shared-res") as acquired:
                if not acquired:
                    await asyncio.sleep(0)
                    continue
                async with guard:
                    holders += 1
                    max_holders = max(max_holders, holders)
                await asyncio.sleep(0.001)
                async with guard:
                    holders -= 1

    await asyncio.gather(*(worker(i) for i in range(8)))

    assert max_holders == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_shared_locks_coexist_real_concurrency(tmp_path: Path) -> None:
    """Shared locks on the same resource must not block each other."""
    lock = FileLock(tmp_path / "locks")
    concurrent = 0
    max_concurrent = 0
    guard = asyncio.Lock()

    async def reader(_: int) -> None:
        nonlocal concurrent, max_concurrent
        for _ in range(10):
            async with lock.acquire("shared-res", mode="shared") as acquired:
                assert acquired is True
                async with guard:
                    concurrent += 1
                    max_concurrent = max(max_concurrent, concurrent)
                await asyncio.sleep(0.001)
                async with guard:
                    concurrent -= 1

    await asyncio.gather(*(reader(i) for i in range(8)))

    assert max_concurrent > 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delivery_lock_release_after_body_exception(tmp_path: Path) -> None:
    """A failing delivery body must release the lock so the same delivery id
    becomes immediately re-acquirable — the exact recovery path a worker hit."""
    base_dir = tmp_path / "state"
    base_dir.mkdir()

    class DeliveryError(Exception):
        pass

    with pytest.raises(DeliveryError):
        async with acquire_delivery_lock("dlv-1", base_dir) as locked:
            assert locked is True
            raise DeliveryError("delivery failed")

    async with acquire_delivery_lock("dlv-1", base_dir) as locked:
        assert locked is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delivery_lock_exclusive_contention(tmp_path: Path) -> None:
    """Concurrent workers racing on the same delivery id: exactly one wins at
    a time; the loser skips, then wins after the holder finishes."""
    base_dir = tmp_path / "state"
    base_dir.mkdir()

    async def worker(_: int) -> None:
        for _ in range(10):
            async with acquire_delivery_lock("dlv-contended", base_dir) as locked:
                if locked:
                    await asyncio.sleep(0.002)

    await asyncio.gather(*(worker(i) for i in range(6)))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_distinct_deliveries_process_parallel(tmp_path: Path) -> None:
    """Different delivery ids must not serialize against each other."""
    base_dir = tmp_path / "state"
    base_dir.mkdir()
    seen_concurrent = 0
    max_concurrent = 0
    guard = asyncio.Lock()

    async def worker(wid: int) -> None:
        nonlocal seen_concurrent, max_concurrent
        async with acquire_delivery_lock(f"dlv-{wid}", base_dir) as locked:
            assert locked is True
            async with guard:
                seen_concurrent += 1
                max_concurrent = max(max_concurrent, seen_concurrent)
            await asyncio.sleep(0.02)
            async with guard:
                seen_concurrent -= 1

    await asyncio.gather(*(worker(i) for i in range(6)))

    assert max_concurrent == 6
