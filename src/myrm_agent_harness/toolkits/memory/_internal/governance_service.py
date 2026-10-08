"""Governance-side orchestration for approvals and profile updates.


[INPUT]
- memory._internal.approval::{apply_edited_content, memory_to_pending, pending_to_memory} (POS: approval queue helpers)
- memory._internal.memory_scanner::{scan_and_clean_memory} (POS: content safety scanner)
- memory.protocols.relational::RelationalStoreProtocol (POS: relational store protocol)

[OUTPUT]
- GovernanceService: Governance orchestrator (approval flow, profile updates, scanning)

[POS]
Governance-side orchestration. Handles approval flow, profile updates, and content
scanning. Not part of the public API.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from myrm_agent_harness.toolkits.memory._internal.approval import (
    apply_edited_content,
    memory_to_pending,
    pending_to_memory,
)
from myrm_agent_harness.toolkits.memory._internal.memory_scanner import (
    MemoryTaintedError,
    ScanVerdict,
    get_scan_metrics,
    scan_memory_content,
)
from myrm_agent_harness.toolkits.memory._internal.storage import MemoryError, MemoryNotFoundError
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.protocols.relational import RelationalStoreProtocol
from myrm_agent_harness.toolkits.memory.types import (
    AnyMemory,
    MemoryScope,
    MemoryType,
    PendingRecord,
    PendingResolutionAction,
)

logger = logging.getLogger(__name__)

StoreFunc = Callable[[AnyMemory], Awaitable[AnyMemory]]


class GovernanceService:
    """Owns governance workflows that should not live in MemoryManager."""

    __slots__ = (
        "_config",
        "_namespaces",
        "_relational",
        "_scope",
        "_user_id",
    )

    def __init__(
        self,
        *,
        user_id: str | None,
        config: MemoryConfig,
        relational: RelationalStoreProtocol | None,
        namespaces: list[str],
        scope: MemoryScope,
    ) -> None:
        self._user_id = user_id
        self._config = config
        self._relational = relational
        self._namespaces = list(namespaces)
        self._scope = scope.model_copy(deep=True)

    async def submit_pending(
        self,
        memory: AnyMemory,
        *,
        resolution_action: PendingResolutionAction = PendingResolutionAction.STORE,
        target_memory_id: str | None = None,
        target_content: str | None = None,
    ) -> str:
        rel = self._rel()
        if await rel.pending_exists(memory.memory_type.value, memory.content):
            return ""
        return await rel.submit_pending(
            memory_to_pending(
                memory,
                resolution_action=resolution_action,
                target_memory_id=target_memory_id,
                target_content=target_content,
            )
        )

    async def approve(
        self,
        pending_id: str,
        *,
        store_func: StoreFunc,
        correct_func: Callable[[str, str], Awaitable[AnyMemory]],
        forget_func: Callable[[str], Awaitable[AnyMemory]],
        edited_content: str | None = None,
    ) -> AnyMemory | None:
        """Apply a pending proposal; ``edited_content`` is the reviewer's rewording.

        ``forget_func`` retires the targeted memory (archive, not hard delete) so
        a mistaken approval stays restorable during the archive retention window.
        """
        rel = self._rel()
        record = await rel.get_pending(pending_id)
        if record is None:
            raise MemoryNotFoundError(f"Pending record {pending_id} not found")
        if edited_content is not None:
            record = apply_edited_content(record, edited_content)
        if record.memory_type == MemoryType.PROFILE:
            data = record.memory_data
            scope_data = data.get("scope")
            scope = MemoryScope.model_validate(scope_data) if isinstance(scope_data, dict) else self._scope
            await rel.set_profile(str(data.get("key", "")), str(data.get("value", "")), scope=scope)
            await rel.mark_pending(pending_id, "approved")
            return None

        if record.resolution_action == PendingResolutionAction.DELETE:
            if record.target_memory_id:
                try:
                    await forget_func(record.target_memory_id)
                except MemoryNotFoundError:
                    # Already forgotten or purged while queued: the user's intent
                    # (this fact is gone) already holds, so approval stays idempotent.
                    logger.warning("Forget target %s is already gone; approving as a no-op", record.target_memory_id)
            await rel.mark_pending(pending_id, "approved")
            return None

        if record.resolution_action == PendingResolutionAction.CORRECT and record.target_memory_id:
            try:
                stored = await correct_func(record.target_memory_id, record.content)
            except MemoryNotFoundError:
                # The fact the user asked to correct was forgotten or purged while
                # the proposal sat in the queue. Approval must still honour the
                # confirmed correction: keep it as a new memory instead of failing.
                logger.warning(
                    "Correction target %s is gone; storing the approved correction as a new memory",
                    record.target_memory_id,
                )
                stored = await store_func(pending_to_memory(record))
            await rel.mark_pending(pending_id, "approved")
            return stored

        stored = await store_func(pending_to_memory(record))
        await rel.mark_pending(pending_id, "approved")
        return stored

    async def reject(self, pending_id: str) -> None:
        await self._rel().mark_pending(pending_id, "rejected")

    async def list_pending(self, *, limit: int) -> list[PendingRecord]:
        return await self._rel().list_pending(limit=limit)

    async def count_pending(self) -> int:
        return await self._rel().count_pending()

    async def batch_approve(
        self, pending_ids: list[str], *, approve_func: Callable[[str], Awaitable[AnyMemory | None]]
    ) -> tuple[int, list[str]]:
        success = 0
        failed: list[str] = []
        for pending_id in pending_ids:
            try:
                await approve_func(pending_id)
                success += 1
            except Exception as exc:
                logger.warning("Batch approve failed for %s: %s", pending_id, exc)
                failed.append(pending_id)
        return success, failed

    async def batch_reject(self, pending_ids: list[str]) -> int:
        return await self._rel().batch_mark_pending(pending_ids, "rejected")

    async def set_profile_attribute(self, key: str, value: str, *, approval_required: bool) -> str | None:
        if self._config.security_scan_enabled:
            result = scan_memory_content(value, block_threshold=self._config.injection_block_threshold)
            get_scan_metrics().record(result.verdict)
            if result.verdict == ScanVerdict.BLOCKED:
                raise MemoryTaintedError(result.injection_score, result.injection_patterns)
            if result.cleaned_text != value:
                value = result.cleaned_text

        rel = self._rel()

        # Profile entries should always be visible across conversations.
        # We bind them to the agent scope (or global if agent isn't available)
        # so they aren't isolated to a single conversation/task.
        profile_scope = self._scope.model_copy(deep=True)
        if len(self._namespaces) > 1:
            # namespaces[0] is global, namespaces[1] is agent
            profile_scope.primary_namespace = self._namespaces[1]
            profile_scope.namespaces = self._namespaces[:2]
            profile_scope.channel_id = None
            profile_scope.conversation_id = None
            profile_scope.task_id = None
        elif self._namespaces:
            profile_scope.primary_namespace = self._namespaces[0]
            profile_scope.namespaces = [self._namespaces[0]]
            profile_scope.agent_id = None
            profile_scope.channel_id = None
            profile_scope.conversation_id = None
            profile_scope.task_id = None

        if approval_required:
            record = PendingRecord(
                memory_type=MemoryType.PROFILE,
                content=f"{key}: {value}",
                memory_data={"key": key, "value": value, "scope": profile_scope.model_dump()},
            )
            if await rel.pending_exists(MemoryType.PROFILE.value, record.content):
                return ""
            return await rel.submit_pending(record)

        await rel.set_profile(key, value, scope=profile_scope)
        return None

    async def get_profile_attribute(self, key: str) -> str | None:
        return await self._rel().get_profile(key, namespaces=self._namespaces)

    def _rel(self) -> RelationalStoreProtocol:
        if self._relational is None:
            raise MemoryError("Relational backend required")
        return self._relational
