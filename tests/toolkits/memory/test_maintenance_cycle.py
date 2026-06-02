"""Tests for MemoryManager.run_maintenance_cycle() and MaintenanceReport.

Covers:
- Empty system maintenance
- Consolidation + forgetting + health orchestration
- Lock-based mutual exclusion (skip if already running)
- Graceful error handling (each step independent)
- MaintenanceReport structure and to_dict()
- Public API import
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.health import MaintenanceReport
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument
from myrm_agent_harness.toolkits.memory.types import (
    ClaimConflictState,
    ClaimGraphState,
    DigestKind,
    EvaporationState,
    MemoryTier,
)


def _make_doc(
    *,
    doc_id: str = "doc-1",
    user_id: str = "test-user",
    days_ago: int = 1,
    importance: float = 0.5,
    access_count: int = 5,
) -> VectorDocument:
    now = datetime.now(UTC)
    created = now - timedelta(days=days_ago)
    return VectorDocument(
        id=doc_id,
        content=f"test memory {doc_id}",
        embedding=[0.1] * 10,
        metadata={
            "memory_type": "semantic",
            "importance": importance,
            "confidence": 1.0,
            "access_count": access_count,
            "created_at": created.isoformat(),
            "updated_at": created.isoformat(),
            "last_accessed_at": "",
            "archived": False,
            "tags": "[]",
            "preference_type": "",
            "preference_strength": 0.0,
            "source_chat_id": "",
            "source_message_id": "",
            "correction_of": "",
            "source_error": "",
            "language": "en",
            "merge_count": 0,
            "merge_history": "",
        },
    )


def _create_manager(
    memory_config: MemoryConfig,
    mock_vector_store: AsyncMock,
    mock_embedding: AsyncMock,
    consolidation_llm: object | None = None,
    mock_relational_store: AsyncMock | None = None,
) -> MemoryManager:
    return MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store,
        embedding=mock_embedding,
        relational=mock_relational_store,
        consolidation_llm=consolidation_llm,
        auto_warmup=False,
    )


class TestMaintenanceReport:
    def test_empty_report(self) -> None:
        report = MaintenanceReport()
        assert report.skipped is False
        assert report.consolidation_merged == 0
        assert report.forgotten_count == 0
        assert report.health is None

    def test_skipped_report(self) -> None:
        report = MaintenanceReport(skipped=True, skip_reason="already running")
        assert report.skipped is True
        assert report.skip_reason == "already running"

    def test_to_dict_structure(self) -> None:
        report = MaintenanceReport(
            consolidation_merged=2, consolidation_corrected=1, forgotten_count=5, archived_count=3, duration_ms=150.0
        )
        d = report.to_dict()
        assert d["consolidation"]["merged"] == 2
        assert d["consolidation"]["corrected"] == 1
        assert d["digests"]["evaporated"] == 0
        assert d["claim_graph"]["compiled"] == 0
        assert d["forgetting"]["forgotten"] == 5
        assert d["forgetting"]["archived"] == 3
        assert d["duration_ms"] == 150.0
        assert d["health"] is None
        assert d["skipped"] is False

    def test_frozen_immutable(self) -> None:
        report = MaintenanceReport()
        with pytest.raises(AttributeError):
            report.consolidation_merged = 10  # type: ignore[misc]


class TestRunMaintenanceCycle:
    @pytest.mark.asyncio
    async def test_empty_system(
        self, memory_config: MemoryConfig, mock_vector_store: AsyncMock, mock_embedding: AsyncMock
    ) -> None:
        mock_vector_store.scroll.return_value = []
        mock_vector_store.count.return_value = 0

        mgr = _create_manager(memory_config, mock_vector_store, mock_embedding)
        report = await mgr.run_maintenance_cycle()

        assert isinstance(report, MaintenanceReport)
        assert report.skipped is False
        assert report.health is not None
        assert report.health.total == 100
        assert report.duration_ms > 0

    @pytest.mark.asyncio
    async def test_forgetting_runs(
        self, memory_config: MemoryConfig, mock_vector_store: AsyncMock, mock_embedding: AsyncMock
    ) -> None:
        docs = [_make_doc(doc_id=f"d-{i}", days_ago=1) for i in range(3)]
        mock_vector_store.scroll.return_value = docs
        mock_vector_store.count.return_value = 3

        mgr = _create_manager(memory_config, mock_vector_store, mock_embedding)
        report = await mgr.run_maintenance_cycle()

        assert isinstance(report, MaintenanceReport)
        assert report.health is not None

    @pytest.mark.asyncio
    async def test_task_digests_evaporated(
        self, memory_config: MemoryConfig, mock_vector_store: AsyncMock, mock_embedding: AsyncMock
    ) -> None:
        digest_doc = _make_doc(doc_id="digest-1")
        digest_doc.metadata["memory_type"] = "episodic"
        digest_doc.metadata["event_type"] = "task_digest"
        digest_doc.metadata["memory_tier"] = MemoryTier.L2.value
        digest_doc.metadata["digest_kind"] = DigestKind.TASK.value
        digest_doc.metadata["evaporation_state"] = EvaporationState.PENDING.value

        async def _scroll(*args, **kwargs):
            filters = kwargs.get("filters", {})
            if (
                filters.get("event_type") == "task_digest"
                and filters.get("evaporation_state") == EvaporationState.PENDING.value
            ):
                return [digest_doc], None
            return [], None

        mock_vector_store.scroll.side_effect = _scroll
        mock_vector_store.count.return_value = 1

        mgr = _create_manager(memory_config, mock_vector_store, mock_embedding)
        report = await mgr.run_maintenance_cycle()

        assert report.digests_evaporated == 1
        upsert_docs = mock_vector_store.upsert.call_args_list[0].args[1]
        assert upsert_docs[0].metadata["evaporation_state"] == EvaporationState.EVAPORATED.value
        assert "evaporated_at" in upsert_docs[0].metadata
        assert upsert_docs[0].metadata["claim_graph_state"] == ClaimGraphState.PENDING.value
        assert upsert_docs[0].metadata["claim_graph_conflict"] == ClaimConflictState.NONE.value

    @pytest.mark.asyncio
    async def test_claim_graph_compiled_from_evaporated_digest(
        self,
        memory_config: MemoryConfig,
        mock_vector_store: AsyncMock,
        mock_embedding: AsyncMock,
        mock_graph_store: AsyncMock,
    ) -> None:
        digest_doc = _make_doc(doc_id="digest-claim-1")
        digest_doc.content = (
            "**Title**: Auth task\n"
            "**Goal**: Add JWT authentication\n"
            "**Result**: Completed implementation\n"
            "**Key Details**: auth/jwt.py created"
        )
        digest_doc.metadata["memory_type"] = "episodic"
        digest_doc.metadata["event_type"] = "task_digest"
        digest_doc.metadata["memory_tier"] = MemoryTier.L2.value
        digest_doc.metadata["digest_kind"] = DigestKind.TASK.value
        digest_doc.metadata["evaporation_state"] = EvaporationState.EVAPORATED.value
        digest_doc.metadata["claim_graph_state"] = ClaimGraphState.PENDING.value
        digest_doc.metadata["primary_namespace"] = "channel:test-user:telegram"
        digest_doc.metadata["namespaces"] = ["global:test-user", "channel:test-user:telegram"]
        digest_doc.metadata["channel_id"] = "telegram"

        async def _scroll(*args, **kwargs):
            filters = kwargs.get("filters", {})
            if (
                filters.get("event_type") == "task_digest"
                and filters.get("evaporation_state") == EvaporationState.PENDING.value
            ):
                return [], None
            if (
                filters.get("event_type") == "task_digest"
                and filters.get("evaporation_state") == EvaporationState.EVAPORATED.value
            ):
                return [digest_doc], None
            return [], None

        mock_vector_store.scroll.side_effect = _scroll
        mock_vector_store.count.return_value = 1
        mock_graph_store.get_or_create_node.side_effect = [
            mock_graph_store.get_or_create_node.return_value.__class__(
                id="evidence:digest-claim-1", labels=["Evidence"], properties={"source_memory_id": "digest-claim-1"}
            ),
            mock_graph_store.get_or_create_node.return_value.__class__(
                id="claim:test-user:channel-test-user-telegram:auth-task",
                labels=["Claim"],
                properties={
                    "user_id": "test-user",
                    "primary_namespace": "channel:test-user:telegram",
                    "claim_key": "auth-task",
                    "evidence_count": 0,
                    "contradiction_count": 0,
                    "contradiction_status": "none",
                    "result_polarity": "positive",
                },
            ),
        ]

        mgr = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store,
            embedding=mock_embedding,
            graph=mock_graph_store,
            auto_warmup=False,
        )
        report = await mgr.run_maintenance_cycle()

        assert report.claims_compiled == 1
        assert mock_graph_store.get_or_create_node.await_count == 2
        assert mock_graph_store.create_relationship.await_count == 1
        assert mock_graph_store.update_node_properties.await_count == 1

        compiled_upsert = mock_vector_store.upsert.call_args_list[0].args[1]
        assert compiled_upsert[0].metadata["claim_graph_state"] == ClaimGraphState.COMPILED.value
        assert (
            compiled_upsert[0].metadata["claim_graph_node_id"] == "claim:test-user:channel-test-user-telegram:auth-task"
        )
        assert compiled_upsert[0].metadata["claim_graph_conflict"] == ClaimConflictState.NONE.value
        update_call = mock_graph_store.update_node_properties.await_args
        assert "Latest result: Completed implementation" in update_call.args[1]["model_summary"]
        assert "Evidence count: 1" in update_call.args[1]["model_summary"]
        assert update_call.args[1]["latest_relationship_type"] == "SUPPORTED_BY"
        assert update_call.args[1]["primary_namespace"] == "channel:test-user:telegram"
        assert update_call.args[1]["scope_namespaces_json"] == "global:test-user|channel:test-user:telegram"

    @pytest.mark.asyncio
    async def test_claim_graph_marks_contradiction_and_refreshes_freshness(
        self,
        memory_config: MemoryConfig,
        mock_vector_store: AsyncMock,
        mock_embedding: AsyncMock,
        mock_graph_store: AsyncMock,
    ) -> None:
        digest_doc = _make_doc(doc_id="digest-claim-2", days_ago=0)
        digest_doc.content = (
            "**Title**: Auth task\n"
            "**Goal**: Add JWT authentication\n"
            "**Result**: Failed rollout\n"
            "**Key Details**: production login broken"
        )
        digest_doc.metadata["memory_type"] = "episodic"
        digest_doc.metadata["event_type"] = "task_digest"
        digest_doc.metadata["memory_tier"] = MemoryTier.L2.value
        digest_doc.metadata["digest_kind"] = DigestKind.TASK.value
        digest_doc.metadata["evaporation_state"] = EvaporationState.EVAPORATED.value
        digest_doc.metadata["claim_graph_state"] = ClaimGraphState.PENDING.value
        digest_doc.metadata["primary_namespace"] = "channel:test-user:telegram"
        digest_doc.metadata["namespaces"] = ["global:test-user", "channel:test-user:telegram"]
        digest_doc.metadata["channel_id"] = "telegram"

        async def _scroll(*args, **kwargs):
            filters = kwargs.get("filters", {})
            if (
                filters.get("event_type") == "task_digest"
                and filters.get("evaporation_state") == EvaporationState.PENDING.value
            ):
                return [], None
            if (
                filters.get("event_type") == "task_digest"
                and filters.get("evaporation_state") == EvaporationState.EVAPORATED.value
            ):
                return [digest_doc], None
            return [], None

        mock_vector_store.scroll.side_effect = _scroll
        mock_vector_store.count.return_value = 1
        node_cls = mock_graph_store.get_or_create_node.return_value.__class__
        mock_graph_store.get_or_create_node.side_effect = [
            node_cls(
                id="evidence:digest-claim-2", labels=["Evidence"], properties={"source_memory_id": "digest-claim-2"}
            ),
            node_cls(
                id="claim:test-user:channel-test-user-telegram:auth-task",
                labels=["Claim"],
                properties={
                    "user_id": "test-user",
                    "primary_namespace": "channel:test-user:telegram",
                    "claim_key": "auth-task",
                    "evidence_count": 2,
                    "contradiction_count": 0,
                    "contradiction_status": "none",
                    "result_polarity": "positive",
                    "freshness_days": 45,
                    "freshness": "stale",
                },
            ),
        ]
        mock_graph_store.update_node_properties.side_effect = lambda node_id, properties: node_cls(
            id=node_id, labels=["Claim"], properties=properties
        )

        mgr = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store,
            embedding=mock_embedding,
            graph=mock_graph_store,
            auto_warmup=False,
        )
        report = await mgr.run_maintenance_cycle()

        assert report.claims_compiled == 1
        relationship_call = mock_graph_store.create_relationship.await_args
        assert relationship_call.args[2] == "CONTRADICTED_BY"

        update_call = mock_graph_store.update_node_properties.await_args
        assert update_call.args[1]["contradiction_status"] == "conflicted"
        assert update_call.args[1]["contradiction_count"] == 1
        assert update_call.args[1]["freshness_days"] == 0
        assert update_call.args[1]["freshness"] == "fresh"
        assert update_call.args[1]["latest_channel_id"] == "telegram"
        assert update_call.args[1]["latest_relationship_type"] == "CONTRADICTED_BY"

        compiled_upsert = mock_vector_store.upsert.call_args_list[0].args[1]
        assert compiled_upsert[0].metadata["claim_graph_conflict"] == ClaimConflictState.CONFLICTED.value

    @pytest.mark.asyncio
    async def test_claim_graph_marks_superseded_relationship_for_migration(
        self,
        memory_config: MemoryConfig,
        mock_vector_store: AsyncMock,
        mock_embedding: AsyncMock,
        mock_graph_store: AsyncMock,
    ) -> None:
        digest_doc = _make_doc(doc_id="digest-claim-3", days_ago=0)
        digest_doc.content = (
            "**Title**: Deploy task\n"
            "**Goal**: Standardize deployment strategy\n"
            "**Result**: Migrated from Docker Compose to Kubernetes\n"
            "**Key Details**: switch to Helm rollout instead of compose stack"
        )
        digest_doc.metadata["memory_type"] = "episodic"
        digest_doc.metadata["event_type"] = "task_digest"
        digest_doc.metadata["memory_tier"] = MemoryTier.L2.value
        digest_doc.metadata["digest_kind"] = DigestKind.TASK.value
        digest_doc.metadata["evaporation_state"] = EvaporationState.EVAPORATED.value
        digest_doc.metadata["claim_graph_state"] = ClaimGraphState.PENDING.value
        digest_doc.metadata["primary_namespace"] = "channel:test-user:telegram"
        digest_doc.metadata["namespaces"] = ["global:test-user", "channel:test-user:telegram"]
        digest_doc.metadata["channel_id"] = "telegram"

        async def _scroll(*args, **kwargs):
            filters = kwargs.get("filters", {})
            if (
                filters.get("event_type") == "task_digest"
                and filters.get("evaporation_state") == EvaporationState.PENDING.value
            ):
                return [], None
            if (
                filters.get("event_type") == "task_digest"
                and filters.get("evaporation_state") == EvaporationState.EVAPORATED.value
            ):
                return [digest_doc], None
            return [], None

        mock_vector_store.scroll.side_effect = _scroll
        mock_vector_store.count.return_value = 1
        node_cls = mock_graph_store.get_or_create_node.return_value.__class__
        mock_graph_store.get_or_create_node.side_effect = [
            node_cls(
                id="evidence:digest-claim-3", labels=["Evidence"], properties={"source_memory_id": "digest-claim-3"}
            ),
            node_cls(
                id="claim:test-user:channel-test-user-telegram:deploy-task",
                labels=["Claim"],
                properties={
                    "user_id": "test-user",
                    "primary_namespace": "channel:test-user:telegram",
                    "claim_key": "deploy-task",
                    "goal": "Standardize deployment strategy",
                    "key_details": "use docker compose baseline",
                    "evidence_count": 1,
                    "contradiction_count": 0,
                    "contradiction_status": "none",
                    "result_polarity": "positive",
                    "last_result": "Use Docker Compose for deployment",
                },
            ),
        ]
        mock_graph_store.update_node_properties.side_effect = lambda node_id, properties: node_cls(
            id=node_id, labels=["Claim"], properties=properties
        )

        mgr = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store,
            embedding=mock_embedding,
            graph=mock_graph_store,
            auto_warmup=False,
        )
        report = await mgr.run_maintenance_cycle()

        assert report.claims_compiled == 1
        relationship_call = mock_graph_store.create_relationship.await_args
        assert relationship_call.args[2] == "SUPERSEDED_BY"

        update_call = mock_graph_store.update_node_properties.await_args
        assert update_call.args[1]["contradiction_status"] == "conflicted"
        assert update_call.args[1]["contradiction_count"] == 1
        assert update_call.args[1]["latest_relationship_type"] == "SUPERSEDED_BY"

    @pytest.mark.asyncio
    async def test_lock_prevents_concurrent(
        self, memory_config: MemoryConfig, mock_vector_store: AsyncMock, mock_embedding: AsyncMock
    ) -> None:
        mock_vector_store.scroll.return_value = []
        mock_vector_store.count.return_value = 0

        mgr = _create_manager(memory_config, mock_vector_store, mock_embedding)

        async with mgr._maintenance_lock:
            report = await mgr.run_maintenance_cycle()

        assert report.skipped is True
        assert report.skip_reason == "already running"

    @pytest.mark.asyncio
    async def test_forgetting_error_handled(
        self, memory_config: MemoryConfig, mock_vector_store: AsyncMock, mock_embedding: AsyncMock
    ) -> None:
        mock_vector_store.scroll.side_effect = RuntimeError("DB error")
        mock_vector_store.count.return_value = 0

        mgr = _create_manager(memory_config, mock_vector_store, mock_embedding)
        report = await mgr.run_maintenance_cycle()

        assert isinstance(report, MaintenanceReport)
        assert report.forgotten_count == 0

    @pytest.mark.asyncio
    async def test_health_error_handled(
        self, memory_config: MemoryConfig, mock_vector_store: AsyncMock, mock_embedding: AsyncMock
    ) -> None:
        mock_vector_store.scroll.return_value = []
        mock_vector_store.count.side_effect = RuntimeError("count failed")

        mgr = _create_manager(memory_config, mock_vector_store, mock_embedding)
        report = await mgr.run_maintenance_cycle()

        assert isinstance(report, MaintenanceReport)

    @pytest.mark.asyncio
    async def test_to_dict_roundtrip(
        self, memory_config: MemoryConfig, mock_vector_store: AsyncMock, mock_embedding: AsyncMock
    ) -> None:
        mock_vector_store.scroll.return_value = []
        mock_vector_store.count.return_value = 0

        mgr = _create_manager(memory_config, mock_vector_store, mock_embedding)
        report = await mgr.run_maintenance_cycle()
        d = report.to_dict()

        assert isinstance(d, dict)
        assert "consolidation" in d
        assert "forgetting" in d
        assert "health" in d
        assert "duration_ms" in d

    @pytest.mark.asyncio
    async def test_force_skips_time_gate(
        self, memory_config: MemoryConfig, mock_vector_store: AsyncMock, mock_embedding: AsyncMock
    ) -> None:
        """force=True should bypass should_consolidate time gate."""
        mock_vector_store.scroll.return_value = []
        mock_vector_store.count.return_value = 0

        mock_relational = AsyncMock()
        mock_consolidation_llm = AsyncMock()

        mgr = _create_manager(
            memory_config,
            mock_vector_store,
            mock_embedding,
            consolidation_llm=mock_consolidation_llm,
            mock_relational_store=mock_relational,
        )

        from myrm_agent_harness.toolkits.memory.strategies.consolidation import ConsolidationStats

        mock_should = AsyncMock(return_value=False)
        mock_run = AsyncMock(return_value=ConsolidationStats(merged=3, corrected=1, updated=2, errors=0))

        with (
            patch("myrm_agent_harness.toolkits.memory.strategies.consolidation.should_consolidate", mock_should),
            patch("myrm_agent_harness.toolkits.memory.strategies.consolidation.run_consolidation", mock_run),
        ):
            report_normal = await mgr.run_maintenance_cycle(force=False)
            assert report_normal.consolidation_merged == 0
            assert mock_should.call_count == 1
            assert mock_run.call_count == 0

            mock_should.reset_mock()
            mock_run.reset_mock()

            report_forced = await mgr.run_maintenance_cycle(force=True)
            assert mock_should.call_count == 0
            assert report_forced.consolidation_merged == 3

    @pytest.mark.asyncio
    async def test_public_api_import(self) -> None:
        from myrm_agent_harness.toolkits.memory import MaintenanceReport as PublicReport

        assert PublicReport is MaintenanceReport
