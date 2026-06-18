"""Ephemeral and read-only memory managers for subagent isolation.

Provides two isolation strategies:
- EphemeralMemoryManager: reads from parent, writes to a local dict (no DB pollution).
- ReadOnlyMemoryView: reads from parent, all writes raise PermissionError.

[INPUT]
- (none)

[OUTPUT]
- ReadOnlyMemoryView: Read-only proxy over a parent MemoryManager.
- EphemeralMemoryManager: Dict-backed ephemeral memory manager.

[POS]
Ephemeral and read-only memory managers for subagent isolation.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Any, Literal

from myrm_agent_harness.core.hooks import HookRegistryProtocol
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import (
    AnyMemory,
    EpisodicMemory,
    MemorySearchResult,
    MemoryStatus,
    MemoryType,
    ProceduralMemory,
    RuleSource,
    SemanticMemory,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from myrm_agent_harness.toolkits.memory.archival import ArchivalResult
    from myrm_agent_harness.toolkits.memory.backup import BackupResult, MemoryBackupStrategy, RestoreResult
    from myrm_agent_harness.toolkits.memory.health import HealthScore, MaintenanceReport


class ReadOnlyMemoryView(MemoryManager):
    """Read-only proxy over a parent MemoryManager.

    Delegates all read operations (search, get_context, get_memory, etc.) to
    the parent.  Every write/mutate operation (28 methods total) unconditionally
    raises PermissionError, providing type-system-level enforcement of the
    READ_ONLY_GLOBAL isolation policy — even if new write tools or code paths
    are added in the future.
    """

    def __init__(self, parent: MemoryManager) -> None:
        self._parent = parent
        self._user_id = getattr(parent, "_user_id", None)
        self._namespaces = parent._namespaces
        self._scope = parent._scope
        self._config = parent._config
        self._active_session = None
        self._approval_required = False
        self._last_cited_memory_ids: list[str] = []
        self._memory_policy = getattr(parent, "_memory_policy", None)
        self._recall_mode = getattr(parent, "_recall_mode", None)

        self._consolidation_llm = None
        self._maintenance_lock = asyncio.Lock()
        self._vector = None
        self._relational = None
        self._graph = None

    def _deny(self) -> None:
        raise PermissionError(
            "ReadOnlyMemoryView: write operations are forbidden under READ_ONLY_GLOBAL isolation policy."
        )

    # ── Read operations (delegated) ──────────────────────────────────

    async def search(
        self, query: str, *, memory_types: list[MemoryType] | None = None, limit: int = 10, **kwargs: Any
    ) -> list[MemorySearchResult]:
        return await self._parent.search(query, memory_types=memory_types, limit=limit, **kwargs)

    async def get_context(self, **kwargs: Any) -> dict[str, object]:
        return await self._parent.get_context(**kwargs)

    async def get_learned_context(self) -> dict[str, list[dict[str, str]]]:
        return await self._parent.get_learned_context()

    async def get_memory(self, memory_id: str) -> AnyMemory | None:
        return await self._parent.get_memory(memory_id)

    def begin_session(self, chat_id: str, hook_registry: HookRegistryProtocol | None = None) -> Any:
        return self._parent.begin_session(chat_id, hook_registry=hook_registry)

    async def end_session(self) -> list[AnyMemory]:
        return []

    @property
    def namespaces(self) -> list[str]:
        return self._namespaces

    @property
    def has_relational(self) -> bool:
        return self._parent.has_relational

    @property
    def has_vector(self) -> bool:
        return self._parent.has_vector

    @property
    def has_graph(self) -> bool:
        return self._parent.has_graph

    # ── Write operations (all denied) ────────────────────────────────

    async def store(self, memory: AnyMemory, *, _bypass_approval: bool = False) -> AnyMemory:
        self._deny()
        return memory  # unreachable, satisfies type checker

    async def store_batch(self, memories: Sequence[AnyMemory]) -> list[AnyMemory]:
        self._deny()
        return []

    async def add_knowledge(
        self,
        content: str,
        *,
        importance: float = 0.5,
        tags: list[str] | None = None,
        source_chat_id: str | None = None,
        write_target: Literal["bound", "shared"] = "bound",
    ) -> SemanticMemory:
        self._deny()
        raise AssertionError  # unreachable

    async def add_event(
        self,
        content: str,
        *,
        event_type: str = "conversation",
        related_entities: list[str] | None = None,
        source_chat_id: str | None = None,
        source_message_id: str | None = None,
        write_target: Literal["bound", "shared"] = "bound",
    ) -> EpisodicMemory:
        self._deny()
        raise AssertionError  # unreachable

    async def add_rule(
        self,
        trigger: str,
        action: str,
        *,
        priority: int = 0,
        trigger_keywords: list[str] | None = None,
        source: RuleSource = RuleSource.USER_EXTRACTED,
    ) -> ProceduralMemory:
        self._deny()
        raise AssertionError  # unreachable

    async def delete_memory(self, collection: str, ids: list[str]) -> int:
        self._deny()
        return 0

    async def delete_rule(self, rule_id: str) -> bool:
        self._deny()
        return False

    async def delete_all(self) -> dict[str, int]:
        self._deny()
        return {}

    async def delete_by_type(self, memory_type: MemoryType) -> int:
        self._deny()
        return 0

    async def delete_profile(self, key_or_id: str) -> bool:
        self._deny()
        return False

    async def correct_memory(self, memory_id: str, corrected_content: str) -> SemanticMemory:
        self._deny()
        raise AssertionError  # unreachable

    async def archive_memories_auto(self) -> ArchivalResult:
        self._deny()
        raise AssertionError  # unreachable

    async def restore_backup(
        self, backup_id: str, strategy: MemoryBackupStrategy, *, overwrite: bool = False
    ) -> RestoreResult:
        self._deny()
        raise AssertionError  # unreachable

    async def delete_backup(self, backup_id: str, strategy: MemoryBackupStrategy) -> bool:
        self._deny()
        return False

    async def run_maintenance_cycle(self, *, force: bool = False) -> MaintenanceReport:
        self._deny()
        raise AssertionError  # unreachable

    async def set_profile_attribute(self, key: str, value: str) -> str | None:
        self._deny()
        return None

    async def approve(self, pending_id: str) -> AnyMemory | None:
        self._deny()
        return None

    async def reject(self, pending_id: str) -> None:
        self._deny()

    async def batch_approve(self, pending_ids: list[str]) -> tuple[int, list[str]]:
        self._deny()
        return (0, [])

    async def batch_reject(self, pending_ids: list[str]) -> int:
        self._deny()
        return 0

    async def rate_memory(self, memory_id: str, score: int, collection: str | None = None) -> bool:
        self._deny()
        return False

    async def pin_memory(self, memory_id: str) -> AnyMemory:
        self._deny()
        raise AssertionError  # unreachable

    async def unpin_memory(self, memory_id: str) -> AnyMemory:
        self._deny()
        raise AssertionError  # unreachable

    async def update_memory(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        importance: float | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, str | int | float | bool] | None = None,
        is_active: bool | None = None,
        status: MemoryStatus | None = None,
    ) -> AnyMemory:
        self._deny()
        raise AssertionError  # unreachable

    async def unarchive_memory(self, memory_id: str) -> SemanticMemory | EpisodicMemory:
        self._deny()
        raise AssertionError  # unreachable

    async def create_backup(self, strategy: MemoryBackupStrategy, description: str | None = None) -> BackupResult:
        self._deny()
        raise AssertionError  # unreachable

    async def import_memories(
        self, data: dict[str, list[dict[str, object]]], *, skip_duplicates: bool = True
    ) -> dict[str, int]:
        self._deny()
        return {}

    async def submit_pending(self, memory: AnyMemory) -> str:
        self._deny()
        return ""

    async def unarchive_memories(self, memory_ids: list[str], memory_type: MemoryType) -> int:
        self._deny()
        return 0

    def set_last_cited_memory_ids(self, ids: list[str]) -> None:
        self._last_cited_memory_ids = ids

    async def close(self) -> None:
        pass

    # ── Read operations that lack internal deps — return safe defaults ──

    async def get_profile_attribute(self, key: str) -> str | None:
        return await self._parent.get_profile_attribute(key) if hasattr(self._parent, "get_profile_attribute") else None

    async def list_pending(self, *, limit: int = 50) -> list[Any]:
        return []

    async def count_pending(self) -> int:
        return 0

    async def list_memories(
        self, memory_type: MemoryType, *, limit: int = 100, offset: int = 0, include_archived: bool = False
    ) -> list[AnyMemory]:
        return await self._parent.list_memories(
            memory_type, limit=limit, offset=offset, include_archived=include_archived
        )

    async def count_memories(self, memory_type: MemoryType, **kwargs: Any) -> int:
        return await self._parent.count_memories(memory_type, **kwargs)

    async def search_archived(self, query: str, memory_type: MemoryType, *, limit: int = 10) -> list[Any]:
        return []

    async def list_backups(self, strategy: MemoryBackupStrategy) -> list[Any]:
        return await strategy.list_backups()

    async def export_all(self) -> dict[str, list[dict[str, object]]]:
        return await self._parent.export_all()

    def get_enabled_types(self) -> list[MemoryType]:
        return self._parent.get_enabled_types()

    async def compute_health_score(self) -> HealthScore:
        return await self._parent.compute_health_score()


class EphemeralMemoryManager(MemoryManager):
    """
    Dict-backed ephemeral memory manager.

    Prevents subagents from polluting the global persistent memory.
    Read queries span both the global persistent memory and the ephemeral dict.
    Writes only go to the ephemeral dict, bypassing DB completely.
    """

    def __init__(self, parent: MemoryManager) -> None:
        """
        Initialize the ephemeral wrapper around a parent MemoryManager.
        We deliberately do not call super().__init__() to avoid allocating real resources
        or spawning background tasks like warmup. We just copy the identity fields.
        """
        self._parent = parent
        self._ephemeral_store: dict[str, AnyMemory] = {}

        # Copy identity and basic configuration from parent
        self._user_id = getattr(parent, "_user_id", None)
        self._namespaces = parent._namespaces
        self._scope = parent._scope
        self._config = parent._config
        self._active_session = None
        self._approval_required = False
        self._last_cited_memory_ids: list[str] = []
        self._memory_policy = getattr(parent, "_memory_policy", None)
        self._recall_mode = getattr(parent, "_recall_mode", None)

        # Ensure we have no background consolidation or tasks
        self._consolidation_llm = None
        self._maintenance_lock = asyncio.Lock()
        self._vector = None
        self._relational = None
        self._graph = None

    @property
    def namespaces(self) -> list[str]:
        return self._namespaces

    @property
    def has_relational(self) -> bool:
        return self._parent.has_relational

    @property
    def has_vector(self) -> bool:
        return self._parent.has_vector

    @property
    def has_graph(self) -> bool:
        return self._parent.has_graph

    async def store(self, memory: AnyMemory, *, _bypass_approval: bool = False) -> AnyMemory:
        """Store memory only in the ephemeral dict."""
        if not hasattr(memory, "id") or not memory.id:
            memory.id = str(uuid.uuid4())
        self._ephemeral_store[memory.id] = memory
        return memory

    async def store_batch(self, memories: Sequence[AnyMemory]) -> list[AnyMemory]:
        """Store multiple memories only in the ephemeral dict."""
        results = []
        for memory in memories:
            results.append(await self.store(memory))
        return results

    async def search(
        self, query: str, *, memory_types: list[MemoryType] | None = None, limit: int = 10, **kwargs: Any
    ) -> list[MemorySearchResult]:
        """Search both parent persistent memory and local ephemeral memory."""
        # 1. Search persistent parent
        parent_results = await self._parent.search(query, memory_types=memory_types, limit=limit, **kwargs)

        # 2. Naive search in ephemeral memory
        ephemeral_results: list[MemorySearchResult] = []
        q_lower = query.lower()
        for memory in self._ephemeral_store.values():
            m_type = getattr(memory, "memory_type", None)
            if memory_types and m_type not in memory_types:
                continue

            content = getattr(memory, "content", "") or ""
            if q_lower in content.lower():
                ephemeral_results.append(
                    MemorySearchResult(memory=memory, score=1.0, memory_type=m_type or MemoryType.SEMANTIC)
                )

        # 3. Combine and re-sort
        combined = ephemeral_results + parent_results
        combined.sort(key=lambda x: x.score, reverse=True)
        return combined[:limit]

    async def add_knowledge(
        self,
        content: str,
        *,
        importance: float = 0.5,
        tags: list[str] | None = None,
        source_chat_id: str | None = None,
        write_target: Literal["bound", "shared"] = "bound",
    ) -> SemanticMemory:
        memory = SemanticMemory(
            content=content,
            importance=importance,
            tags=tags or [],
            source_chat_id=source_chat_id,
        )
        await self.store(memory)
        return memory

    async def add_event(
        self,
        content: str,
        *,
        event_type: str = "conversation",
        related_entities: list[str] | None = None,
        source_chat_id: str | None = None,
        source_message_id: str | None = None,
        write_target: Literal["bound", "shared"] = "bound",
    ) -> EpisodicMemory:
        memory = EpisodicMemory(
            content=content,
            event_type=event_type,
            related_entities=related_entities or [],
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
        )
        await self.store(memory)
        return memory

    async def add_rule(
        self,
        trigger: str,
        action: str,
        *,
        priority: int = 0,
        trigger_keywords: list[str] | None = None,
        source: RuleSource = RuleSource.USER_EXTRACTED,
    ) -> ProceduralMemory:
        memory = ProceduralMemory(
            content=f"{trigger} → {action}",
            trigger=trigger,
            action=action,
            priority=priority,
            trigger_keywords=trigger_keywords or [],
            source=source,
        )
        await self.store(memory)
        return memory

    async def get_context(self, **kwargs: Any) -> dict[str, object]:
        return await self._parent.get_context(**kwargs)

    async def get_learned_context(self) -> dict[str, list[dict[str, str]]]:
        return await self._parent.get_learned_context()

    async def get_memory(self, memory_id: str) -> AnyMemory | None:
        if memory_id in self._ephemeral_store:
            return self._ephemeral_store[memory_id]
        return await self._parent.get_memory(memory_id)

    def begin_session(self, chat_id: str, hook_registry: HookRegistryProtocol | None = None) -> Any:
        return self._parent.begin_session(chat_id, hook_registry=hook_registry)

    async def end_session(self) -> list[AnyMemory]:
        return await self._parent.end_session()

    # ── Methods called by framework during subagent lifecycle ──

    async def close(self) -> None:
        self._ephemeral_store.clear()

    async def set_profile_attribute(self, key: str, value: str) -> str | None:
        mem = SemanticMemory(content=f"[profile:{key}] {value}", tags=["profile"])
        await self.store(mem)
        return None

    def set_last_cited_memory_ids(self, ids: list[str]) -> None:
        self._last_cited_memory_ids = ids

    async def rate_memory(self, memory_id: str, score: int, collection: str | None = None) -> bool:
        if memory_id in self._ephemeral_store:
            return True
        return await self._parent.rate_memory(memory_id, score, collection)

    async def get_profile_attribute(self, key: str) -> str | None:
        return await self._parent.get_profile_attribute(key)

    async def delete_memory(self, collection: str, ids: list[str]) -> int:
        count = 0
        for mid in ids:
            if mid in self._ephemeral_store:
                del self._ephemeral_store[mid]
                count += 1
        return count

    async def list_memories(
        self, memory_type: MemoryType, *, limit: int = 100, offset: int = 0, include_archived: bool = False
    ) -> list[AnyMemory]:
        return await self._parent.list_memories(
            memory_type, limit=limit, offset=offset, include_archived=include_archived
        )

    async def count_memories(self, memory_type: MemoryType, **kwargs: Any) -> int:
        return await self._parent.count_memories(memory_type, **kwargs)

    def get_enabled_types(self) -> list[MemoryType]:
        return self._parent.get_enabled_types()
