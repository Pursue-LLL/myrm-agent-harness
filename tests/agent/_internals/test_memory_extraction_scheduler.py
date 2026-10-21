"""Unit tests for per-chat memory extraction coalescing."""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.agent._internals import memory_extraction_scheduler as sched


@pytest.fixture(autouse=True)
def _clear_scheduler_tasks() -> None:
    sched._chat_extract_tasks.clear()
    yield
    sched._chat_extract_tasks.clear()


@pytest.mark.asyncio
async def test_schedule_cancels_superseded_extraction_for_same_chat() -> None:
    started_first = asyncio.Event()
    release_first = asyncio.Event()
    first_ran = False
    second_ran = False

    async def first() -> None:
        nonlocal first_ran
        started_first.set()
        await release_first.wait()
        first_ran = True

    async def second() -> None:
        nonlocal second_ran
        second_ran = True

    sched.schedule_chat_memory_extraction("chat-coalesce-1", first)
    await asyncio.wait_for(started_first.wait(), timeout=2.0)
    sched.schedule_chat_memory_extraction("chat-coalesce-1", second)
    release_first.set()
    await asyncio.sleep(0.05)

    assert second_ran is True
    assert first_ran is False


@pytest.mark.asyncio
async def test_schedule_ignores_blank_chat_id() -> None:
    ran = False

    async def run() -> None:
        nonlocal ran
        ran = True

    sched.schedule_chat_memory_extraction("", run)
    sched.schedule_chat_memory_extraction(None, run)
    await asyncio.sleep(0.02)
    assert ran is False
