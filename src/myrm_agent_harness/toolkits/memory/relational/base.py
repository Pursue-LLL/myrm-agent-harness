"""Relational Store Abstract Interface.


[INPUT]
myrm_agent_harness.toolkits.memory.types (POS: Memory type definitions)

[OUTPUT]
RelationalStore: Abstract async relational store interface (Profile + Procedural + Pending)

[POS]
Relational store abstraction layer. Defines a backend-agnostic relational storage interface
for all relational store implementations. Defaults to SQLite; PostgreSQL/SQLAlchemy optional.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from myrm_agent_harness.toolkits.memory.types import (
    MemoryScope,
    PendingRecord,
    ProceduralMemory,
    ProfileAttributeSnapshot,
    ProfileEntry,
)


class RelationalStore(ABC):
    """Abstract async relational store for Profile, Procedural, and Pending memories.

    Provides a unified API for structured memory persistence,
    supporting different backends (SQLite, PostgreSQL, etc.).

    Example::

        store = SQLiteRelationalStore(db_path="~/.app/relational.db")

        await store.set_profile("user-1", "language", "zh")
        lang = await store.get_profile("user-1", "language")

        rule = ProceduralMemory(
            user_id="user-1", content="...",
            trigger="user asks for file", action="use Excel format"
        )
        await store.create_rule("user-1", rule)
        await store.close()
    """

    # ── Profile ──────────────────────────────────────────────────────

    @abstractmethod
    async def get_profile(self, key: str, *, namespaces: list[str] | None = None) -> str | None: ...

    @abstractmethod
    async def get_profile_snapshot(
        self, key: str, *, namespaces: list[str] | None = None
    ) -> ProfileAttributeSnapshot: ...

    @abstractmethod
    async def set_profile(self, key: str, value: str, *, scope: MemoryScope | None = None) -> None: ...

    @abstractmethod
    async def delete_profile(self, key: str, *, namespaces: list[str] | None = None) -> bool: ...

    @abstractmethod
    async def list_profiles(
        self, *, limit: int = 1000, offset: int = 0, namespaces: list[str] | None = None
    ) -> list[ProfileEntry]: ...

    @abstractmethod
    async def count_profiles(self, *, namespaces: list[str] | None = None) -> int: ...

    # ── Procedural rules ─────────────────────────────────────────────

    @abstractmethod
    async def create_rule(self, rule: ProceduralMemory) -> ProceduralMemory: ...

    @abstractmethod
    async def get_rule(self, rule_id: str, *, namespaces: list[str] | None = None) -> ProceduralMemory | None: ...

    @abstractmethod
    async def search_rules(
        self, query: str, *, limit: int = 10, namespaces: list[str] | None = None
    ) -> list[ProceduralMemory]: ...

    @abstractmethod
    async def list_rules(
        self, *, active_only: bool = True, limit: int = 1000, offset: int = 0, namespaces: list[str] | None = None
    ) -> list[ProceduralMemory]: ...

    @abstractmethod
    async def count_rules(self, *, active_only: bool = True, namespaces: list[str] | None = None) -> int: ...

    @abstractmethod
    async def list_rules_by_tool(
        self,
        tool_name: str,
        *,
        active_only: bool = True,
        limit: int = 30,
        namespaces: list[str] | None = None,
    ) -> list[ProceduralMemory]: ...

    @abstractmethod
    async def update_rule(self, rule_id: str, rule: ProceduralMemory) -> ProceduralMemory: ...

    @abstractmethod
    async def delete_rule(self, rule_id: str) -> bool: ...

    @abstractmethod
    async def delete_all(self) -> int: ...

    # ── Pending (approval queue) ─────────────────────────────────────

    @abstractmethod
    async def submit_pending(self, record: PendingRecord) -> str: ...

    @abstractmethod
    async def get_pending(self, pending_id: str) -> PendingRecord | None: ...

    @abstractmethod
    async def pending_exists(self, memory_type: str, content: str) -> bool: ...

    @abstractmethod
    async def mark_pending(self, pending_id: str, status: str) -> None: ...

    @abstractmethod
    async def list_pending(self, *, limit: int = 50) -> list[PendingRecord]: ...

    @abstractmethod
    async def count_pending(self) -> int: ...

    @abstractmethod
    async def batch_mark_pending(self, pending_ids: list[str], status: str) -> int: ...

    @abstractmethod
    async def delete_pending_by_source_chat_id(self, source_chat_id: str) -> int: ...

    @abstractmethod
    async def count_pending_by_source_chat_id(self, source_chat_id: str) -> int: ...

    # ── Lifecycle ────────────────────────────────────────────────────

    @abstractmethod
    async def close(self) -> None: ...

    async def __aenter__(self) -> RelationalStore:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: object
    ) -> None:
        await self.close()
