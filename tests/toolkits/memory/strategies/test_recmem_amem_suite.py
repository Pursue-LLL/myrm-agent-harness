"""Comprehensive Evaluation Suite for RecurrenceDetector, LocalWorkingMemoryBlock and A-MEM Zettelkasten.

Evaluates:
1. RecurrenceDetector trivial chitchat gating, soft deprecation, and eviction priority.
2. LocalWorkingMemoryBlock step lifecycle, smooth sliding flush, and markdown prompt rendering.
3. AMemZettelkastenNetwork evidence-conclusion decoupling, bidirectional links, and lineage evolution.
4. LongMemEval 5-dimensional benchmark protocol simulation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.context_management.working_memory.block import (
    LocalWorkingMemoryBlock,
)
from myrm_agent_harness.agent.context_management.working_memory.types import (
    SubtaskStatus,
    WorkingMemoryFlushResult,
)
from myrm_agent_harness.toolkits.memory.cards import (
    AMemCard,
    AMemZettelkastenNetwork,
)
from myrm_agent_harness.toolkits.memory.consolidation import WorkingMemorySnapshot
from myrm_agent_harness.toolkits.memory.strategies.recurrence import (
    RecurrenceDetector,
    _is_trivial_summary,
)
from myrm_agent_harness.toolkits.memory.types import EvidenceReference
from myrm_agent_harness.toolkits.vector.base import SearchResult, VectorDocument

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_embedding() -> AsyncMock:
    emb = AsyncMock()
    emb.dimension = 768
    emb.embed = AsyncMock(return_value=[0.05] * 768)
    emb.embed_batch = AsyncMock(return_value=[[0.05] * 768])
    return emb


@pytest.fixture
def mock_vector() -> AsyncMock:
    vec = AsyncMock()
    vec.ensure_collection = AsyncMock()
    vec.upsert = AsyncMock(return_value=["doc-id-1"])
    vec.search = AsyncMock(return_value=[])
    vec.count = AsyncMock(return_value=3)
    vec.scroll = AsyncMock(return_value=([], None))
    vec.delete = AsyncMock(return_value=1)
    return vec


@pytest.fixture
def detector(mock_embedding: AsyncMock, mock_vector: AsyncMock) -> RecurrenceDetector:
    return RecurrenceDetector(
        embedding=mock_embedding,
        vector=mock_vector,
        collection_prefix="test_memory",
        similarity_threshold=0.75,
        recurrence_k=2,
        buffer_capacity=10,
        soft_deprecation=True,
    )


# ---------------------------------------------------------------------------
# 1. RecurrenceDetector Enhancements Test
# ---------------------------------------------------------------------------


class TestRecurrenceDetectorEnhancements:
    def test_trivial_greeting_detection(self) -> None:
        assert _is_trivial_summary("hello")
        assert _is_trivial_summary("Hi there!")
        assert _is_trivial_summary("你好呀")
        assert _is_trivial_summary("好的，收到")
        assert _is_trivial_summary("Thanks a lot")
        assert not _is_trivial_summary("User prefers TypeScript with strict mode enabled")
        assert not _is_trivial_summary(
            "Database connection timeout occurs under 100 concurrent clients"
        )

    @pytest.mark.asyncio
    async def test_trivial_greeting_short_circuits_no_vector_call(
        self,
        detector: RecurrenceDetector,
        mock_vector: AsyncMock,
        mock_embedding: AsyncMock,
    ) -> None:
        result = await detector.check_recurrence("你好")
        assert not result.triggered
        assert result.consolidated_content is None
        mock_embedding.embed.assert_not_called()
        mock_vector.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_soft_deprecation_flow_preserves_lineage(
        self, detector: RecurrenceDetector, mock_vector: AsyncMock
    ) -> None:
        existing_doc = VectorDocument(
            id="hist-doc-1",
            content="User prefers async python code",
            vector=[0.05] * 768,
            metadata={"session_id": "sess-old", "importance": 0.5, "is_deprecated": False},
        )
        mock_vector.search.return_value = [
            SearchResult(document=existing_doc, score=0.88)
        ]

        mock_llm = AsyncMock(
            return_value="Consolidated: User strictly prefers asyncio over threading"
        )
        result = await detector.check_recurrence(
            "User prefers async python everywhere", llm_func=mock_llm
        )
        assert result.triggered
        assert "asyncio" in str(result.consolidated_content)

        # Vector delete should NOT be called because soft_deprecation=True
        mock_vector.delete.assert_not_called()

        # Vector upsert should have been called twice:
        # 1. Updating hist-doc-1 with is_deprecated=True
        # 2. Saving the new entry
        assert mock_vector.upsert.call_count >= 2

    @pytest.mark.asyncio
    async def test_vector_search_filters_deprecated_entries(
        self, detector: RecurrenceDetector, mock_vector: AsyncMock
    ) -> None:
        deprecated_doc = VectorDocument(
            id="hist-doc-deprecated",
            content="User prefers async python code",
            vector=[0.05] * 768,
            metadata={"is_deprecated": True, "superseded_by": "new-doc-1"},
        )
        mock_vector.search.return_value = [
            SearchResult(document=deprecated_doc, score=0.92)
        ]
        result = await detector.check_recurrence("User prefers async python code")
        # Since the hit was deprecated, effective hits should be 0 (< recurrence_k=2)
        assert not result.triggered


# ---------------------------------------------------------------------------
# 2. LocalWorkingMemoryBlock System Test
# ---------------------------------------------------------------------------


class TestLocalWorkingMemoryBlockSystem:
    def setup_method(self) -> None:
        LocalWorkingMemoryBlock.reset()

    def teardown_method(self) -> None:
        LocalWorkingMemoryBlock.reset()

    def test_step_lifecycle_and_milestones(self) -> None:
        state = LocalWorkingMemoryBlock.initialize(goal="Refactor Storage Engine")
        state.goal = "Migrate SQLite queries to parameterized CTE statements"

        s1 = LocalWorkingMemoryBlock.add_subtask("Audit legacy SQL queries")
        assert s1 is not None
        assert s1.status == SubtaskStatus.PENDING

        LocalWorkingMemoryBlock.update_subtask(s1.id, status=SubtaskStatus.IN_PROGRESS)
        assert state.subtasks[0].status == SubtaskStatus.IN_PROGRESS

        LocalWorkingMemoryBlock.update_subtask(
            s1.id, status=SubtaskStatus.COMPLETED, notes="Found 12 un-parameterized queries"
        )
        assert state.subtasks[0].status == SubtaskStatus.COMPLETED
        assert state.subtasks[0].notes == "Found 12 un-parameterized queries"

        LocalWorkingMemoryBlock.record_trap(
            "sql_syntax_error",
            "Raw string concatenation causes syntax errors with single quotes",
        )
        assert len(state.traps) == 1

        LocalWorkingMemoryBlock.set_scratchpad("compatibility", "Do not break SQLite 3.35 compatibility")
        assert len(state.scratchpad) == 1

    def test_smooth_sliding_flush_stale(self) -> None:
        LocalWorkingMemoryBlock.initialize(goal="Preserve core objective at all costs")
        LocalWorkingMemoryBlock.record_trap("production_guard", "Never drop production table")

        # Add 10 completed steps
        for i in range(10):
            item = LocalWorkingMemoryBlock.add_subtask(
                f"Step description number {i:02d} with extra verbosity to consume tokens"
            )
            assert item is not None
            LocalWorkingMemoryBlock.update_subtask(item.id, SubtaskStatus.COMPLETED)

        # Add one in-progress step
        active_step = LocalWorkingMemoryBlock.add_subtask("Currently active step that must never be flushed")
        assert active_step is not None
        LocalWorkingMemoryBlock.update_subtask(active_step.id, SubtaskStatus.IN_PROGRESS)

        res: WorkingMemoryFlushResult = LocalWorkingMemoryBlock.flush_stale(flush_ratio=0.5)
        assert res.evicted_subtasks_count > 0
        assert res.estimated_tokens_after <= res.estimated_tokens_before

        # Verify active step and goal are retained
        state = LocalWorkingMemoryBlock.get_state()
        assert state is not None
        step_ids = [s.id for s in state.subtasks]
        assert active_step.id in step_ids
        assert state.goal == "Preserve core objective at all costs"
        assert any("Never drop production table" in t.avoidance_rule for t in state.traps)

    def test_prefix_cache_friendly_turn_tail_render(self) -> None:
        LocalWorkingMemoryBlock.initialize(goal="Ensure deterministic Markdown generation")
        LocalWorkingMemoryBlock.add_subtask("Step 1")
        LocalWorkingMemoryBlock.set_scratchpad("framework", "Myrmidon Harness")

        rendered = LocalWorkingMemoryBlock.format_turn_tail_markdown()
        assert "<working_board>" in rendered
        assert "</working_board>" in rendered
        assert "**Goal**: Ensure deterministic Markdown generation" in rendered
        assert "timestamp" not in rendered.lower()  # Protection against cache thrashing

    def test_to_working_memory_snapshot(self) -> None:
        LocalWorkingMemoryBlock.initialize(goal="Export to consolidation snapshot")
        s = LocalWorkingMemoryBlock.add_subtask("Build component")
        assert s is not None
        LocalWorkingMemoryBlock.update_subtask(s.id, SubtaskStatus.COMPLETED, notes="Component built successfully")
        LocalWorkingMemoryBlock.record_trap("concurrency_hazard", "Watch out for thread safety in async event loop")

        snapshot = LocalWorkingMemoryBlock.to_snapshot()
        assert isinstance(snapshot, WorkingMemorySnapshot)
        assert snapshot.goal == "Export to consolidation snapshot"
        assert len(snapshot.subtasks) == 1
        assert snapshot.subtasks[0].title == "Build component"
        assert snapshot.subtasks[0].completed is True
        assert len(snapshot.traps) == 1
        assert "thread safety" in snapshot.traps[0].avoidance_rule


# ---------------------------------------------------------------------------
# 3. AMemZettelkastenNetwork Test
# ---------------------------------------------------------------------------


class TestAMemZettelkastenNetwork:
    def test_card_creation_and_evidence_anchoring(self) -> None:
        evidence = EvidenceReference(
            source_id="sess-001",
            quote_snippet="User requested strict PEP8 compliance without Any types",
        )
        card = AMemCard(
            id="c-pep8",
            title="Strict PEP8 Type Hint Rule",
            conclusion="Never use Any type annotations in production code",
            evidences=[evidence],
            tags={"typing", "pep8", "code_quality"},
        )
        assert card.evidences[0].source_id == "sess-001"
        assert card.is_active
        assert card.version == 1

    def test_bidirectional_linking(self) -> None:
        net = AMemZettelkastenNetwork()
        ev = EvidenceReference(source_id="sess-001", quote_snippet="test")

        c1 = AMemCard(id="c-core", title="Architecture Core", conclusion="Domain Layer", evidences=[ev])
        c2 = AMemCard(id="c-store", title="Storage Adapter", conclusion="SQLite Repo", evidences=[ev])
        net.add_card(c1)
        net.add_card(c2)

        net.link(c1.id, c2.id)

        assert c2.id in c1.links
        assert c1.id in net.traverse_subgraph([c2.id])

    def test_immutable_evolution_chain(self) -> None:
        net = AMemZettelkastenNetwork()
        ev1 = EvidenceReference(source_id="sess-001", quote_snippet="Prefer dict")
        ev2 = EvidenceReference(source_id="sess-002", quote_snippet="Use Pydantic models")

        c1 = AMemCard(id="c-schema-1", title="Schema Definition", conclusion="Use TypedDict", evidences=[ev1])
        net.add_card(c1)

        c2 = net.evolve(
            old_card_id=c1.id,
            new_conclusion="Use Pydantic BaseModel with strict validation",
            new_evidences=[ev2],
            title="Schema Definition V2",
            reason="Adopt strict typing",
        )
        assert c2 is not None

        assert not c1.is_active
        assert c1.superseded_by == c2.id
        assert c2.supersedes == c1.id
        assert c2.version == 2
        assert c2.is_active

        lineage = net.get_lineage(c1.id)
        assert len(lineage) == 2
        assert lineage[0].id == c1.id
        assert lineage[1].id == c2.id

    def test_subgraph_traversal_and_depth_guard(self) -> None:
        net = AMemZettelkastenNetwork()
        ev = EvidenceReference(source_id="sess-001", quote_snippet="test")

        c1 = AMemCard(id="c-1", title="Node 1", conclusion="Root", evidences=[ev])
        c2 = AMemCard(id="c-2", title="Node 2", conclusion="Mid", evidences=[ev])
        c3 = AMemCard(id="c-3", title="Node 3", conclusion="Leaf", evidences=[ev])

        net.add_card(c1)
        net.add_card(c2)
        net.add_card(c3)

        net.link(c1.id, c2.id)
        net.link(c2.id, c3.id)

        # Depth 1 traversal
        sub_d1 = net.traverse_subgraph([c1.id], max_depth=1)
        assert len(sub_d1) == 2
        assert c3.id not in sub_d1

        # Depth 2 traversal
        sub_d2 = net.traverse_subgraph([c1.id], max_depth=2)
        assert len(sub_d2) == 3

    def test_export_markdown_digest(self) -> None:
        net = AMemZettelkastenNetwork()
        ev = EvidenceReference(source_id="sess-001", quote_snippet="We use uv for deps")
        c = AMemCard(
            id="c-uv",
            title="Dependency Manager",
            conclusion="Package manager is uv",
            evidences=[ev],
            tags={"tooling"},
        )
        net.add_card(c)

        digest = net.export_digest([c.id])
        assert "## Related Knowledge Cards" in digest
        assert "Dependency Manager" in digest
        assert "Package manager is uv" in digest


# ---------------------------------------------------------------------------
# 4. LongMemEval Benchmark Protocol Simulation (5 Dimensions)
# ---------------------------------------------------------------------------


class TestLongMemEvalBenchmarkProtocol:
    def test_dimension_1_recall_accuracy(self) -> None:
        """Dim 1: Recall Accuracy >= 95% on structured memory network."""
        net = AMemZettelkastenNetwork()
        ev = EvidenceReference(source_id="sess-bench", quote_snippet="bench")

        created_ids = []
        for i in range(20):
            c = AMemCard(
                id=f"card-{i:02d}",
                title=f"Entity Topic {i:02d}",
                conclusion=f"Detailed spec for subsystem {i:02d}",
                evidences=[ev],
                tags={f"tag_{i}"},
            )
            net.add_card(c)
            created_ids.append(c.id)

        # Query simulation across created items
        hits = 0
        for cid in created_ids:
            found = net.get_card(cid)
            if found is not None and found.is_active:
                hits += 1

        recall_acc = hits / len(created_ids)
        assert recall_acc >= 0.95, f"Recall accuracy {recall_acc:.2%} is below 95%"

    def test_dimension_2_conflict_resolution_fidelity(self) -> None:
        """Dim 2: Conflict resolution certainty (evolved versions win deterministically)."""
        net = AMemZettelkastenNetwork()
        ev_old = EvidenceReference(source_id="sess-old", quote_snippet="Use port 8000")
        ev_new = EvidenceReference(source_id="sess-new", quote_snippet="Switch to port 8080")

        old_card = AMemCard(
            id="c-port-old",
            title="Server Port",
            conclusion="Port 8000",
            evidences=[ev_old],
        )
        net.add_card(old_card)

        new_card = net.evolve(
            old_card_id=old_card.id,
            new_conclusion="Port 8080",
            new_evidences=[ev_new],
            title="Server Port",
        )
        assert new_card is not None

        # Retrieval without deprecated cards returns exactly 1 latest verdict
        active_subgraph_ids = net.traverse_subgraph([new_card.id], active_only=True)
        assert len(active_subgraph_ids) == 1
        active_card = net.get_card(next(iter(active_subgraph_ids)))
        assert active_card is not None
        assert active_card.conclusion == "Port 8080"
        assert old_card.is_active is False

    def test_dimension_3_lineage_traceability_completeness(self) -> None:
        """Dim 3: 100% causal lineage traceability to raw evidence anchor."""
        net = AMemZettelkastenNetwork()
        ev = EvidenceReference(
            source_id="sess-999",
            quote_snippet="Fatal: deadlock in db lock",
        )

        v1 = AMemCard(id="c-v1", title="Lock Rule", conclusion="v1 rule", evidences=[ev])
        net.add_card(v1)
        v2 = net.evolve(v1.id, "v2 rule", new_evidences=[ev])
        assert v2 is not None
        v3 = net.evolve(v2.id, "v3 rule", new_evidences=[ev])
        assert v3 is not None

        # Trace backwards from v3 to the root card and evidence
        lineage = net.get_lineage(v3.id)
        assert len(lineage) == 3
        root = lineage[0]
        assert root.id == v1.id
        assert root.evidences[0].source_id == "sess-999"
        assert root.evidences[0].quote_snippet == "Fatal: deadlock in db lock"

    def test_dimension_4_non_destructive_retention_rate(self) -> None:
        """Dim 4: Critical constraints & traps survive multi-round sliding window flushes."""
        LocalWorkingMemoryBlock.reset()
        state = LocalWorkingMemoryBlock.initialize(goal="Mission Critical Objective")
        LocalWorkingMemoryBlock.record_trap("safety_rule", "Critical memory safety rule")

        for round_idx in range(5):
            for step_idx in range(4):
                s = LocalWorkingMemoryBlock.add_subtask(f"Ephemeral step r{round_idx}-s{step_idx}")
                assert s is not None
                LocalWorkingMemoryBlock.update_subtask(s.id, SubtaskStatus.COMPLETED)
            LocalWorkingMemoryBlock.flush_stale(flush_ratio=0.5)

        assert state.goal == "Mission Critical Objective"
        assert any("Critical memory safety rule" in t.avoidance_rule for t in state.traps)
        assert len(state.traps) == 1
        # Completed subtasks must have been smoothly evicted instead of growing to 20
        assert len(state.subtasks) < 20

    def test_dimension_5_noise_suppression_ratio(self) -> None:
        """Dim 5: 100% noise rejection ratio on chitchat & greetings."""
        chitchat_samples = [
            "hello",
            "Hi there",
            "你好",
            "好的",
            "收到",
            "ok",
            "thank you",
            "thanks",
            " morning ",
            "bye!",
        ]
        suppressed = 0
        for sample in chitchat_samples:
            if _is_trivial_summary(sample):
                suppressed += 1

        suppression_ratio = suppressed / len(chitchat_samples)
        assert (
            suppression_ratio == 1.0
        ), f"Suppression ratio {suppression_ratio:.2%} is below 100%"
