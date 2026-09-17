"""Tests for checkpoint read_access."""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.checkpointing.read_access import read_checkpoint_messages


@pytest.mark.asyncio
async def test_read_checkpoint_messages_none_checkpointer() -> None:
    assert await read_checkpoint_messages(None, "t1") == []


@pytest.mark.asyncio
async def test_read_checkpoint_messages_no_aget() -> None:
    class Dummy:
        pass

    assert await read_checkpoint_messages(Dummy(), "t1") == []


@pytest.mark.asyncio
async def test_read_checkpoint_messages_aget_exception() -> None:
    class FailingCheckpointer:
        async def aget(self, config: dict[str, object]) -> object:
            raise RuntimeError("DB error")

    assert await read_checkpoint_messages(FailingCheckpointer(), "t1") == []


@pytest.mark.asyncio
async def test_read_checkpoint_messages_non_mapping_checkpoint() -> None:
    class NonMappingCheckpointer:
        async def aget(self, config: dict[str, object]) -> object:
            return "not a mapping"

    assert await read_checkpoint_messages(NonMappingCheckpointer(), "t1") == []


@pytest.mark.asyncio
async def test_read_checkpoint_messages_invalid_channel_values() -> None:
    class InvalidChannelValuesCheckpointer:
        async def aget(self, config: dict[str, object]) -> object:
            return {"channel_values": "not a mapping"}

    assert await read_checkpoint_messages(InvalidChannelValuesCheckpointer(), "t1") == []


@pytest.mark.asyncio
async def test_read_checkpoint_messages_messages_not_list() -> None:
    class NonListMessagesCheckpointer:
        async def aget(self, config: dict[str, object]) -> object:
            return {"channel_values": {"messages": "not a list"}}

    assert await read_checkpoint_messages(NonListMessagesCheckpointer(), "t1") == []


@pytest.mark.asyncio
async def test_read_checkpoint_messages_success() -> None:
    expected = [{"type": "human", "content": "hello"}]

    class ValidCheckpointer:
        async def aget(self, config: dict[str, object]) -> object:
            return {"channel_values": {"messages": expected}}

    res = await read_checkpoint_messages(ValidCheckpointer(), "t1")
    assert res == expected
