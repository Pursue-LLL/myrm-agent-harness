"""Unit tests for Anti-Semantic-Aliasing discriminator and MemoryCapacityManager."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.memory.governor.capacity_manager import (
    MemoryCapacityManager,
)
from myrm_agent_harness.toolkits.memory.governor.discriminator import (
    AntiSemanticAliasingDiscriminator,
)
from myrm_agent_harness.toolkits.memory.governor.models import (
    AliasingDecision,
    GovernedMemoryEntry,
    MemorySourceAnchor,
)


class TestAntiSemanticAliasingDiscriminator:
    def test_blocks_cross_workspace_semantic_aliasing(self) -> None:
        discriminator = AntiSemanticAliasingDiscriminator()

        candidate = GovernedMemoryEntry(
            entity="auth_service",
            statement="Authentication runs on port 8080 with mock token",
            confidence=0.95,
            anchor=MemorySourceAnchor(workspace_root="/projects/project_alpha"),
        )
        query_anchor = MemorySourceAnchor(workspace_root="/projects/project_beta")

        # Extremely high raw semantic similarity
        res = discriminator.evaluate(candidate, raw_score=0.98, query_anchor=query_anchor)

        assert res.decision == AliasingDecision.REJECT_CROSS_DOMAIN
        assert res.calibrated_score == 0.0
        assert "Cross-workspace aliasing detected" in res.reason

    def test_allows_same_workspace_retrieval(self) -> None:
        discriminator = AntiSemanticAliasingDiscriminator()

        candidate = GovernedMemoryEntry(
            entity="auth_service",
            statement="Production auth url is https://auth.company.internal",
            confidence=0.90,
            anchor=MemorySourceAnchor(
                workspace_root="/projects/main_repo",
                session_id="session_1",
            ),
        )
        query_anchor = MemorySourceAnchor(
            workspace_root="/projects/main_repo",
            session_id="session_1",
        )

        res = discriminator.evaluate(candidate, raw_score=0.90, query_anchor=query_anchor)

        assert res.decision == AliasingDecision.ACCEPT
        assert res.calibrated_score == pytest.approx(0.81, abs=0.01)

    def test_blocks_incompatible_actor_roles(self) -> None:
        discriminator = AntiSemanticAliasingDiscriminator()

        candidate = GovernedMemoryEntry(
            entity="security_bypass",
            statement="Bypass auth with flag --insecure",
            confidence=0.9,
            anchor=MemorySourceAnchor(
                workspace_root="/projects/app",
                actor_role="untrusted",
            ),
        )
        query_anchor = MemorySourceAnchor(
            workspace_root="/projects/app",
            actor_role="system",
        )

        res = discriminator.evaluate(candidate, raw_score=0.95, query_anchor=query_anchor)

        assert res.decision == AliasingDecision.REJECT_ACTOR_CONFLICT
        assert res.calibrated_score == 0.0

    def test_filter_batch_sorts_and_excludes_aliased(self) -> None:
        discriminator = AntiSemanticAliasingDiscriminator(min_accept_score=0.4)

        query_anchor = MemorySourceAnchor(workspace_root="/projects/app")

        valid_candidate = GovernedMemoryEntry(
            entity="db",
            statement="DB host is localhost",
            confidence=0.9,
            anchor=MemorySourceAnchor(workspace_root="/projects/app"),
        )
        aliased_candidate = GovernedMemoryEntry(
            entity="db",
            statement="Foreign DB host is external.host",
            confidence=0.9,
            anchor=MemorySourceAnchor(workspace_root="/projects/other_system"),
        )

        candidates = [(valid_candidate, 0.9), (aliased_candidate, 0.99)]
        results = discriminator.filter_batch(candidates, query_anchor)

        assert len(results) == 1
        assert results[0].entry.entry_id == valid_candidate.entry_id


class TestMemoryCapacityManager:
    @pytest.mark.asyncio
    async def test_duplicate_registration_reinforces_and_consolidates(self) -> None:
        manager = MemoryCapacityManager(max_capacity=10)
        anchor = MemorySourceAnchor(workspace_root="/app")

        e1 = await manager.register_entry(
            entity="node_version",
            statement="Use Node 20 LTS",
            confidence=0.8,
            anchor=anchor,
        )
        assert e1.access_count == 1
        assert e1.confidence == 0.8

        e2 = await manager.register_entry(
            entity="node_version",
            statement="use node 20 lts",  # case-insensitive match
            confidence=0.8,
            anchor=anchor,
        )
        assert e2.entry_id == e1.entry_id
        assert e2.access_count == 2
        assert e2.confidence == pytest.approx(0.85)

    @pytest.mark.asyncio
    async def test_capacity_telemetry_metrics(self) -> None:
        manager = MemoryCapacityManager(max_capacity=5)
        anchor = MemorySourceAnchor(workspace_root="/app")

        await manager.register_entry("pkg_a", "statement a", anchor=anchor)
        await manager.register_entry("pkg_b", "statement b", anchor=anchor)

        metrics = await manager.get_metrics()
        assert metrics.total_active_entries == 2
        assert metrics.max_capacity == 5
        assert metrics.saturation_ratio == 0.4
        assert metrics.is_over_capacity is False

    @pytest.mark.asyncio
    async def test_auto_eviction_when_capacity_exceeded_with_lock_guard(self) -> None:
        # Max capacity 4, target headroom 0.5 (shrink to 2 entries)
        manager = MemoryCapacityManager(max_capacity=4, target_headroom_ratio=0.5)
        anchor = MemorySourceAnchor(workspace_root="/app")

        # Insert locked critical rule (immune to eviction)
        locked_entry = await manager.register_entry(
            entity="core_rule",
            statement="Never delete production tables",
            confidence=0.5,  # even with low confidence, locked state protects it
            anchor=anchor,
            is_locked=True,
        )

        # Insert 4 disposable entries
        await manager.register_entry("temp_1", "statement 1", confidence=0.2, anchor=anchor)
        await manager.register_entry("temp_2", "statement 2", confidence=0.3, anchor=anchor)
        await manager.register_entry("temp_3", "statement 3", confidence=0.4, anchor=anchor)
        # Registering 5th entry triggers automatic capacity enforcement
        await manager.register_entry("temp_4", "statement 4", confidence=0.9, anchor=anchor)

        entries = await manager.list_active_entries()
        assert len(entries) <= 3

        # Verify locked entry was never evicted
        active_ids = [e.entry_id for e in entries]
        assert locked_entry.entry_id in active_ids

    @pytest.mark.asyncio
    async def test_manual_enforce_capacity(self) -> None:
        manager = MemoryCapacityManager(max_capacity=10, target_headroom_ratio=0.6)
        anchor = MemorySourceAnchor(workspace_root="/repo")

        # Register duplicate entities to test Phase 1 consolidation
        await manager.register_entry("cache", "Use redis", confidence=0.7, anchor=anchor)
        await manager.register_entry("cache", "Use redis cache cluster", confidence=0.9, anchor=anchor)

        report = await manager.enforce_capacity()
        assert report.consolidated_count >= 1

        active = await manager.list_active_entries()
        assert len(active) == 1
        assert active[0].confidence >= 0.9
