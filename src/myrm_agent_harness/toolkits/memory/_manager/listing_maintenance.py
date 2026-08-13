"""MemoryManager mixin module (internal). Do not import directly."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory._internal.storage import (
    _user_filter,
)
from myrm_agent_harness.toolkits.memory._internal.storage import (
    delete_by_type as _delete_by_type,
)
from myrm_agent_harness.toolkits.memory._manager.shared import (
    AnyMemory,
    BackupMetadata,
    BackupResult,
    ConsolidationConfig,
    HealthScore,
    MaintenanceConsolidationResult,
    MaintenanceReport,
    MemoryBackupStrategy,
    MemorySnapshot,
    MemoryType,
    RestoreResult,
    count_by_type,
    datetime,
    list_by_type,
    logger,
    suppress,
)


class MemoryManagerListingMaintenanceMixin:
    # ── List / Count / Delete by type (for API CRUD endpoints) ──

    async def list_memories(
        self,
        memory_type: MemoryType,
        *,
        limit: int = 100,
        offset: int = 0,
        include_archived: bool = False,
        sort_by: str | None = None,
        sort_order: str = "desc",
        tag_filter: str | None = None,
    ) -> list[AnyMemory]:
        return await list_by_type(
            memory_type,
            limit=limit,
            offset=offset,
            relational=self._relational,
            vector=self._vector,
            config=self._config,
            namespaces=self._namespaces,
            include_archived=include_archived,
            sort_by=sort_by,
            sort_order=sort_order,
            tag_filter=tag_filter,
        )

    async def count_memories(
        self, memory_type: MemoryType, *, since: datetime | None = None, tag_filter: str | None = None
    ) -> int:
        return await count_by_type(
            memory_type,
            relational=self._relational,
            vector=self._vector,
            config=self._config,
            namespaces=self._namespaces,
            since=since,
            tag_filter=tag_filter,
        )

    async def delete_by_type(self, memory_type: MemoryType) -> int:
        cascade_ids: list[str] = []
        if (
            memory_type == MemoryType.EPISODIC
            and self._vector is not None
            and self._graph is not None
        ):
            # Claim Graph Evidence/Claim nodes reference episodic task digests, so a
            # bulk clear must cascade-clean derived nodes — matching the single
            # delete path. Collect owned ids first (they are gone after the wipe).
            filters = _user_filter(namespaces=self._namespaces, include_archived=True)
            cascade_ids = [
                memory_id
                for memory_id, owned in await self._collect_vector_ids(
                    self._config.episodic_collection, filters
                )
                if owned
            ]
        deleted = await _delete_by_type(
            memory_type,
            relational=self._relational,
            vector=self._vector,
            config=self._config,
            namespaces=self._namespaces,
        )
        for memory_id in cascade_ids:
            await self._cascade_clean_derived_graph_nodes(memory_id)
        return deleted

    async def _collect_snapshot(self) -> MemorySnapshot | None:
        """Collect a point-in-time count of active semantic + episodic memories."""
        return await self._maintenance_service.collect_snapshot(count_memories_func=self.count_memories)

    async def _scroll_all_memories(self) -> list[AnyMemory]:
        """Scroll all semantic + episodic memories for maintenance analysis."""
        return await self._maintenance_service.scroll_all_memories(
            list_memories_func=lambda memory_type, limit: self.list_memories(memory_type, limit=limit)
        )

    async def compute_health_score(self) -> HealthScore:
        """Compute a quantitative health assessment of this memory instance.

        Low-frequency operation suitable for maintenance cycles, not per-query use.
        """
        return await self._maintenance_service.compute_health_score(
            count_memories_func=self.count_memories,
            list_memories_func=lambda memory_type, limit: self.list_memories(memory_type, limit=limit),
        )

    async def create_backup(self, strategy: MemoryBackupStrategy, description: str | None = None) -> BackupResult:
        """Create a complete memory backup using provided strategy.

        Args:
            strategy: Backup strategy implementation
            description: Optional backup description

        Returns:
            Backup operation result

        Raises:
            ValueError: If vector store not configured
        """

        if not self._vector:
            msg = "Backup requires vector store"
            raise ValueError(msg)

        return await strategy.create_backup(vector=self._vector, relational=self._relational, description=description)

    async def list_backups(self, strategy: MemoryBackupStrategy) -> list[BackupMetadata]:
        """List available backups using provided strategy.

        Args:
            strategy: Backup strategy implementation

        Returns:
            List of backup metadata
        """
        return await strategy.list_backups()

    async def restore_backup(
        self, backup_id: str, strategy: MemoryBackupStrategy, *, overwrite: bool = False
    ) -> RestoreResult:
        """Restore memories from backup using provided strategy.

        Args:
            backup_id: Backup identifier
            strategy: Backup strategy implementation
            overwrite: If True, clear existing memories before restore

        Returns:
            Restore operation result

        Raises:
            ValueError: If vector store not configured
        """

        if not self._vector:
            msg = "Restore requires vector store"
            raise ValueError(msg)

        return await strategy.restore_backup(
            backup_id=backup_id,
            vector=self._vector,
            relational=self._relational,
            overwrite=overwrite,
        )

    async def delete_backup(self, backup_id: str, strategy: MemoryBackupStrategy) -> bool:
        """Delete a backup using provided strategy.

        Args:
            backup_id: Backup identifier
            strategy: Backup strategy implementation

        Returns:
            True if backup deleted successfully
        """
        return await strategy.delete_backup(backup_id=backup_id)

    async def run_maintenance_cycle(self, *, force: bool = False) -> MaintenanceReport:
        """Execute a full maintenance cycle: consolidation → forgetting → staleness review → health check.

        Args:
            force: Skip consolidation time gate (should_consolidate check).
                   Use when the caller explicitly requests maintenance, e.g.
                   user says "organize my memories" or after a bulk import.

        Non-blocking: returns immediately with skipped=True if another cycle
        is already running (via _maintenance_lock).
        """

        return await self._maintenance_service.run_cycle(
            force=force,
            lock=self._maintenance_lock,
            consolidation_enabled=self._consolidation_llm is not None and self.has_vector and self.has_relational,
            collect_snapshot_func=self._collect_snapshot,
            compute_health_func=self.compute_health_score,
            scroll_all_memories_func=self._scroll_all_memories,
            run_consolidation_func=self._run_consolidation_cycle,
            preference_rebuild_func=self._run_preference_rebuild,
            staleness_review_llm=self._consolidation_llm,
        )

    async def _run_consolidation_cycle(self, cfg: ConsolidationConfig, force: bool) -> MaintenanceConsolidationResult:
        if self._consolidation_llm is None:
            return MaintenanceConsolidationResult((0, 0, 0, 0, ()))

        from myrm_agent_harness.toolkits.memory.strategies.consolidation import (
            run_consolidation,
            should_consolidate,
        )

        if not cfg.enabled or not (force or await should_consolidate(self, cfg)):
            return MaintenanceConsolidationResult((0, 0, 0, 0, ()))

        stats = await run_consolidation(
            self,
            self._consolidation_llm,
            cfg,
            on_conflict=self._on_conflict,
            on_complete=self._on_consolidation_complete,
        )
        if stats.merged + stats.corrected + stats.updated > 0:
            from myrm_agent_harness.toolkits.memory.strategies.pattern_discovery import (
                increment_consolidation_count,
            )

            with suppress(Exception):
                await increment_consolidation_count(self)
        return MaintenanceConsolidationResult(
            (stats.merged, stats.corrected, stats.updated, stats.errors, stats.insights)
        )

    async def _run_preference_rebuild(self) -> tuple[int, int, int]:
        """Execute full preference stability rebuild during maintenance.

        After rebuild, writes back stability scores to SemanticMemory.preference_strength
        so the existing retrieval pipeline (get_learned_context, ResultBooster) automatically
        benefits without any modifications.
        """
        if self._preference_strategy is None:
            return (0, 0, 0)
        promoted, demoted, dropped = await self._preference_strategy.full_rebuild()
        await self._writeback_preference_strength()
        return promoted, demoted, dropped

    async def _writeback_preference_strength(self) -> None:
        """Sync stability scores from PreferenceFacet back to SemanticMemory.preference_strength."""
        if self._preference_strategy is None or self._vector is None:
            return
        try:
            all_facets = await self._preference_strategy._store.list_all()
            coll = self._config.semantic_collection
            for facet in all_facets:
                normalized_strength = min(facet.stability / 3.0, 1.0) if not facet.user_pinned else 1.0
                if facet.user_forgotten:
                    normalized_strength = 0.0
                for mid in facet.memory_ids:
                    try:
                        docs = await self._vector.get(coll, [mid])
                        if not docs:
                            continue
                        doc = docs[0]
                        old_strength = doc.metadata.get("preference_strength", 0.0)
                        if abs(float(old_strength) - normalized_strength) < 0.01:
                            continue
                        doc.metadata["preference_strength"] = normalized_strength
                        await self._vector.upsert(coll, [doc])
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("Preference strength writeback failed (non-fatal): %s", e)

    async def delete_profile(self, key_or_id: str) -> bool:
        return await self._rel().delete_profile(key_or_id, namespaces=self._namespaces)
