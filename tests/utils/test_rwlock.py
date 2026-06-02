"""Async tests for myrm_agent_harness.utils.rwlock."""

import asyncio

import pytest

from myrm_agent_harness.utils.rwlock import RWLock


@pytest.mark.asyncio
async def test_read_context_basic() -> None:
    lock = RWLock()
    async with lock.read():
        assert True


@pytest.mark.asyncio
async def test_write_context_basic() -> None:
    lock = RWLock()
    async with lock.write():
        assert True


@pytest.mark.asyncio
async def test_multiple_concurrent_reads() -> None:
    lock = RWLock()

    async def hold() -> None:
        async with lock.read():
            await asyncio.sleep(0.05)

    await asyncio.gather(hold(), hold(), hold())


@pytest.mark.asyncio
async def test_write_excludes_read() -> None:
    lock = RWLock()
    write_ready = asyncio.Event()

    async def writer() -> None:
        await lock.write_acquire()
        write_ready.set()
        await asyncio.sleep(0.12)
        await lock.write_release()

    async def reader() -> None:
        await write_ready.wait()
        await asyncio.wait_for(lock.read_acquire(), timeout=0.3)
        await lock.read_release()

    await asyncio.gather(writer(), reader())


@pytest.mark.asyncio
async def test_write_excludes_write() -> None:
    lock = RWLock()
    first_inside = asyncio.Event()

    async def w1() -> None:
        await lock.write_acquire()
        first_inside.set()
        await asyncio.sleep(0.12)
        await lock.write_release()

    async def w2() -> None:
        await first_inside.wait()
        await asyncio.wait_for(lock.write_acquire(), timeout=0.3)
        await lock.write_release()

    await asyncio.gather(w1(), w2())


@pytest.mark.asyncio
async def test_manual_read_acquire_release() -> None:
    lock = RWLock()
    await lock.read_acquire()
    await lock.read_release()


@pytest.mark.asyncio
async def test_manual_write_acquire_release() -> None:
    lock = RWLock()
    await lock.write_acquire()
    await lock.write_release()
