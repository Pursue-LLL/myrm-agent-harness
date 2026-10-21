"""Memory lifecycle hook protocol.

[INPUT]
- memory.types::{AnyMemory, PendingRecord} (POS: memory data models)

[OUTPUT]
- MemoryTurn: compact turn DTO for lifecycle hooks.
- MemoryLifecycleHookProtocol: optional hook interface around memory runtime events.

[POS]
Memory lifecycle hook protocol. Defines optional callback boundaries for external
memory providers without coupling the framework to product-specific memory stores.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from myrm_agent_harness.toolkits.memory.types import AnyMemory, PendingRecord

MemoryWriteAction = Literal["pending", "stored", "approved", "rejected"]


@dataclass(frozen=True, slots=True)
class MemoryTurn:
    """Compact, provider-neutral conversation turn."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    timestamp: datetime | None = None


@runtime_checkable
class MemoryLifecycleHookProtocol(Protocol):
    """Optional memory lifecycle hooks for pluggable memory providers.

    Implementations may prefetch context, observe writes, preserve salient
    details before compression, and summarize sessions. Hooks are intentionally
    product-neutral and receive only framework DTOs or plain strings.
    """

    async def on_turn_start(self, turn_number: int, message: MemoryTurn) -> str | None: ...

    async def on_memory_write(self, action: MemoryWriteAction, memory: AnyMemory | PendingRecord) -> None: ...

    async def on_delegation(self, task: str, result: str) -> None: ...

    async def on_session_end(self, messages: Sequence[MemoryTurn]) -> None: ...
