"""Multi-tier memory scheduler for cross-storage dispatch and lifecycle management.

[INPUT]
- myrm_agent_harness.toolkits.memory.types::BaseMemory (POS: Memory type system foundation)
- myrm_agent_harness.toolkits.memory.types::MemoryType (POS: Memory type system foundation)
- myrm_agent_harness.toolkits.memory.cube::MemCubeEnvelope (POS: 统一记忆容器契约层。为异构记忆提供标准元数据头、防篡改签名与跨端传输标准。)
- myrm_agent_harness.toolkits.memory.cube::StoragePolicy (POS: 统一记忆容器契约层。为异构记忆提供标准元数据头、防篡改签名与跨端传输标准。)

[OUTPUT]
- MultiTierMemoryScheduler: 多层记忆生命周期调度引擎，统一 L1/L2/L3 分发、封箱导出与防篡改导入

[POS]
多层记忆调度层。负责跨异构存储介质的物理路由、全量信封导出与防篡改恢复落库。
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory.cube import (
    LifecycleTier,
    MemCubeEnvelope,
    StoragePolicy,
    infer_tier_and_policy,
    unwrap_envelope,
    wrap_into_envelope,
)
from myrm_agent_harness.toolkits.memory.types import (
    BaseMemory,
    MemoryType,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager

logger = logging.getLogger(__name__)


class MultiTierMemoryScheduler:
    """Unified scheduler coordinating L1/L2/L3 memories and dispatching storage targets."""

    def __init__(self, memory_manager: MemoryManager | None = None) -> None:
        self._manager = memory_manager

    @property
    def manager(self) -> MemoryManager | None:
        return self._manager

    async def dispatch_store(
        self,
        memory: BaseMemory,
        tier: LifecycleTier | None = None,
        policy: StoragePolicy | None = None,
    ) -> bool:
        """Route memory item to appropriate storage backend based on policy.

        Prevents ValueError exceptions from rigid write services by directly targeting
        the capable backend store.
        """
        resolved_tier, resolved_policy = infer_tier_and_policy(memory)
        tier = tier or resolved_tier
        policy = policy or resolved_policy

        if self._manager is None:
            logger.debug("[SCHEDULER] No memory manager attached, dispatch skipped")
            return False

        # 1. Ephemeral L1 memories stay in active workbench, not persisted
        if policy == StoragePolicy.EPHEMERAL:
            logger.debug("[SCHEDULER] Ephemeral memory %s skipped from disk storage", memory.id)
            return True

        # 2. Relational targets (TaskDigest, Procedural, Conversation)
        if policy == StoragePolicy.RELATIONAL:
            rel_store = getattr(self._manager, "_relational_store", None) or getattr(self._manager, "_relational", None)
            if rel_store is not None and hasattr(rel_store, "save_memory"):
                await rel_store.save_memory(memory)
                logger.debug("[SCHEDULER] Dispatched %s to relational store", memory.id)
                return True

            # Fallback to general manager.store if relational store is unexposed
            try:
                await self._manager.store(memory)
                return True
            except Exception as err:
                logger.warning("[SCHEDULER] Relational dispatch fallback failed: %s", err)
                return False

        # 3. Vector targets (Semantic, Episodic, Integration)
        if policy == StoragePolicy.VECTOR:
            try:
                await self._manager.store(memory)
                logger.debug("[SCHEDULER] Dispatched %s to vector store", memory.id)
                return True
            except Exception as err:
                logger.warning("[SCHEDULER] Vector dispatch failed: %s", err)
                return False

        # 4. Graph targets (Claim)
        if policy == StoragePolicy.GRAPH:
            graph_store = getattr(self._manager, "_graph_store", None)
            if graph_store is not None and hasattr(graph_store, "save_memory"):
                await graph_store.save_memory(memory)
                logger.debug("[SCHEDULER] Dispatched %s to graph store", memory.id)
                return True
            logger.warning("[SCHEDULER] Graph store unavailable for %s", memory.id)
            return False

        return False

    async def export_all_envelopes(
        self,
        limit_per_type: int = 500,
    ) -> list[MemCubeEnvelope[dict[str, object]]]:
        """Collect all memory types across storage tiers and package into sealed envelopes."""
        if self._manager is None:
            return []

        envelopes: list[MemCubeEnvelope[dict[str, object]]] = []

        # 1. Relational items (TaskDigests and Procedural rules)
        rel_store = getattr(self._manager, "_relational_store", None) or getattr(self._manager, "_relational", None)
        if rel_store is not None:
            rel_getter = getattr(rel_store, "list_memories", None) or getattr(rel_store, "get_all", None)
            if rel_getter is not None:
                try:
                    res = rel_getter()
                    all_relational = await res if inspect.isawaitable(res) else res
                    for item in all_relational:
                        if isinstance(item, BaseMemory):
                            envelopes.append(wrap_into_envelope(item, seal_immediately=True))
                except Exception as err:
                    logger.warning("[SCHEDULER] Failed to export relational items: %s", err)

        # 2. Vector items (Semantic, Episodic, Integration)
        for mem_type in (MemoryType.SEMANTIC, MemoryType.EPISODIC, MemoryType.INTEGRATION):
            try:
                vector_items = await self._manager.export_all(memory_types=[mem_type], limit=limit_per_type)
                for item in vector_items:
                    # Avoid duplicate if already collected from relational
                    if any(e.header.cube_id == f"cube_{item.id}" for e in envelopes):
                        continue
                    envelopes.append(wrap_into_envelope(item, seal_immediately=True))
            except Exception as err:
                logger.debug("[SCHEDULER] Export skipped for %s: %s", mem_type, err)

        logger.info("[SCHEDULER] Exported %d sealed MemCube envelopes", len(envelopes))
        return envelopes

    async def import_envelopes(
        self,
        envelopes: Sequence[MemCubeEnvelope[dict[str, object]] | dict[str, object]],
        verify_hashes: bool = True,
    ) -> tuple[int, int]:
        """Restore envelopes back into the appropriate storage tiers.

        Returns:
            tuple of (success_count, failure_or_tampered_count)
        """
        success = 0
        failed = 0

        for raw_env in envelopes:
            env: MemCubeEnvelope[dict[str, object]] = (
                raw_env
                if isinstance(raw_env, MemCubeEnvelope)
                else MemCubeEnvelope[dict[str, object]].model_validate(raw_env)
            )
            if verify_hashes and not env.verify_audit_hash():
                raise ValueError(f"Tamper detected: MemCube audit hash mismatch for {env.header.cube_id}")

            try:
                entity = unwrap_envelope(env)
                dispatched = await self.dispatch_store(
                    memory=entity,
                    tier=env.header.lifecycle_tier,
                    policy=env.header.storage_policy,
                )
                if dispatched:
                    success += 1
                else:
                    failed += 1
            except Exception as err:
                logger.warning("[SCHEDULER] Failed to restore cube %s: %s", env.header.cube_id, err)
                failed += 1

        logger.info("[SCHEDULER] Restored envelopes: %d succeeded, %d failed", success, failed)
        return success, failed
