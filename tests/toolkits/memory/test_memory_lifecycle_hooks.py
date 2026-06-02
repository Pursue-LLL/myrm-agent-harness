"""Tests for memory lifecycle hook protocols."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from myrm_agent_harness.toolkits.memory.protocols import MemoryLifecycleHookProtocol, MemoryTurn
from myrm_agent_harness.toolkits.memory.protocols.hooks import MemoryWriteAction
from myrm_agent_harness.toolkits.memory.types import AnyMemory, PendingRecord, SemanticMemory


class RecordingHook:
    def __init__(self) -> None:
        self.actions: list[MemoryWriteAction] = []

    async def on_turn_start(self, turn_number: int, message: MemoryTurn) -> str | None:
        return f"{turn_number}:{message.role}"

    async def on_memory_write(self, action: MemoryWriteAction, memory: AnyMemory | PendingRecord) -> None:
        self.actions.append(action)

    async def on_delegation(self, task: str, result: str) -> None:
        self.actions.append("stored")

    async def on_session_end(self, messages: Sequence[MemoryTurn]) -> None:
        self.actions.append("approved")


@pytest.mark.asyncio
async def test_memory_lifecycle_hook_protocol_runtime_shape() -> None:
    hook = RecordingHook()
    turn = MemoryTurn(role="user", content="remember customer A")

    assert isinstance(hook, MemoryLifecycleHookProtocol)
    assert await hook.on_turn_start(1, turn) == "1:user"

    await hook.on_memory_write("stored", SemanticMemory(content="customer A prefers concise reports"))
    await hook.on_delegation("summarize", "done")
    await hook.on_session_end([turn])

    assert hook.actions == ["stored", "stored", "approved"]
