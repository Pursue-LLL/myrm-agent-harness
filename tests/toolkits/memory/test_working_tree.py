"""Unit tests for ReTree self-correcting working memory and backtracking pruning engine.

Covers:
- Topological EvidenceTree DAG operations and prefix-preserving bounded slice assembly
- Two-stage FastContradictionDetector (deterministic hash/lexical screening + LLM arbitration)
- TreeRepairEngine atomic 4-step backtracking repair, cascade pruning, and oscillation dampening
- Full lifecycle end-to-end self-correction scenario
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.memory.working_tree import (
    BoundedSummary,
    ConflictType,
    EvidenceNode,
    EvidenceNodeStatus,
    EvidenceSource,
    EvidenceTree,
    FastContradictionDetector,
    TreeRepairEngine,
)


def _make_node(
    node_id: str,
    claim: str,
    summary: str,
    deps: list[str] | None = None,
    content_hash: str = "",
    url: str = "",
) -> EvidenceNode:
    now = datetime.now(UTC).isoformat()
    return EvidenceNode(
        node_id=node_id,
        claim=claim,
        bounded_summary=BoundedSummary(
            summary=summary,
            key_entities=["Python", "FastAPI"],
            key_metrics={"version": "3.12"},
            estimated_tokens=len(summary) // 4,
        ),
        source=EvidenceSource(
            url=url or f"https://example.com/{node_id}",
            title=f"Source for {node_id}",
            snippet=f"Snippet content for {node_id}",
            content_hash=content_hash,
        ),
        dependencies=deps or [],
        dependents=[],
        created_at=now,
        updated_at=now,
    )


class TestEvidenceTree:
    """Tests for DAG topological dependency tracking and bounded slice compilation."""

    def test_tree_initialization(self) -> None:
        tree = EvidenceTree(root_id="root_plan", root_claim="Analyze architecture")
        assert tree.root_id == "root_plan"
        assert "root_plan" in tree.nodes
        assert tree.nodes["root_plan"].claim == "Analyze architecture"

    def test_bidirectional_dependency_wiring(self) -> None:
        tree = EvidenceTree()
        node_a = _make_node("node_a", "Claim A", "Summary A", deps=["root"])
        node_b = _make_node("node_b", "Claim B", "Summary B", deps=["node_a"])
        node_c = _make_node("node_c", "Claim C", "Summary C", deps=["node_b"])

        tree.add_node(node_a)
        tree.add_node(node_b)
        tree.add_node(node_c)

        assert "node_b" in tree.nodes["node_a"].dependents
        assert "node_c" in tree.nodes["node_b"].dependents

        downstream = tree.get_downstream_dependents("node_a")
        assert "node_b" in downstream
        assert "node_c" in downstream

        upstream = tree.get_upstream_dependencies("node_c")
        assert "node_b" in upstream
        assert "node_a" in upstream

    def test_project_sub_tree(self) -> None:
        tree = EvidenceTree()
        node_a = _make_node("node_a", "Claim A", "Summary A", deps=["root"])
        node_b = _make_node("node_b", "Claim B", "Summary B", deps=["node_a"])
        node_unrelated = _make_node("node_x", "Claim X", "Summary X", deps=["root"])

        tree.add_node(node_a)
        tree.add_node(node_b)
        tree.add_node(node_unrelated)

        projected = tree.project_sub_tree(["node_b"])
        assert "node_b" in projected.nodes
        assert "node_a" in projected.nodes
        assert "node_x" not in projected.nodes

    def test_format_bounded_slice_prompt_cache_ordering(self) -> None:
        tree = EvidenceTree()
        node_1 = _make_node("ev_01", "Claim 1", "FastAPI uses Starlette", deps=["root"])
        node_2 = _make_node("ev_02", "Claim 2", "Pydantic v2 has rust core", deps=["root"])
        tree.add_node(node_1)
        tree.add_node(node_2)

        slice_text = tree.format_bounded_slice(max_tokens=1000)
        assert "[ev_01]" in slice_text
        assert "[ev_02]" in slice_text
        assert "EVIDENCE WORKING MEMORY" in slice_text

    def test_serialization_roundtrip(self) -> None:
        tree = EvidenceTree()
        node_a = _make_node("node_a", "Claim A", "Summary A", deps=["root"])
        tree.add_node(node_a)

        data = tree.to_dict()
        reconstructed = EvidenceTree.from_dict(data)
        assert reconstructed.root_id == tree.root_id
        assert "node_a" in reconstructed.nodes
        assert reconstructed.nodes["node_a"].claim == "Claim A"


class TestFastContradictionDetector:
    """Tests for two-stage contradiction and temporal update detection."""

    def test_exact_hash_deduplication(self) -> None:
        detector = FastContradictionDetector()
        existing = [_make_node("ev_01", "Claim 1", "Summary 1", content_hash="hash_123")]

        verdict = detector.check_conflict(
            new_claim="Claim 1 Duplicate",
            new_summary="Summary 1 Duplicate",
            existing_nodes=existing,
            new_content_hash="hash_123",
        )
        assert verdict.conflict_type == ConflictType.NONE
        assert "Exact fingerprint duplicate" in verdict.reason

    def test_deterministic_negation_detection(self) -> None:
        detector = FastContradictionDetector()
        existing = [_make_node("ev_01", "Python GIL is mandatory", "GIL cannot be disabled")]

        verdict = detector.check_conflict(
            new_claim="Python GIL is not mandatory",
            new_summary="PEP 703 proves GIL can be disabled",
            existing_nodes=existing,
        )
        assert verdict.conflict_type == ConflictType.CONTRADICTION
        assert verdict.conflicting_node_id == "ev_01"

    def test_deterministic_temporal_update(self) -> None:
        detector = FastContradictionDetector()
        existing = [_make_node("ev_01", "Release date for 3.12", "Python 3.12 release date")]

        verdict = detector.check_conflict(
            new_claim="Release date for 3.12",
            new_summary="Latest updated version released recently as of 2026",
            existing_nodes=existing,
        )
        assert verdict.conflict_type == ConflictType.TEMPORAL_UPDATE
        assert verdict.conflicting_node_id == "ev_01"

    @pytest.mark.asyncio
    async def test_async_llm_arbitration(self) -> None:
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "VERDICT: CONTRADICTION | REASON: Prior claim refuted by experimental benchmark"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        detector = FastContradictionDetector(arbitrator_llm=mock_llm)
        existing = [_make_node("ev_01", "Redis single threaded", "Redis is strictly single threaded")]

        verdict = await detector.acheck_conflict(
            new_claim="Redis multi threaded",
            new_summary="Redis 6+ introduces I/O multi-threading",
            existing_nodes=existing,
        )
        assert verdict.conflict_type == ConflictType.CONTRADICTION
        assert verdict.conflicting_node_id == "ev_01"
        assert "Prior claim refuted" in verdict.reason


class TestTreeRepairEngine:
    """Tests for 4-step backtracking repair, cascade pruning, and oscillation dampening."""

    def test_temporal_update_preserves_dependents(self) -> None:
        tree = EvidenceTree()
        node_a = _make_node("node_a", "Old Version", "v1.0 released", deps=["root"])
        node_b = _make_node("node_b", "Dependent Doc", "Doc relies on v1.0", deps=["node_a"])
        tree.add_node(node_a)
        tree.add_node(node_b)

        engine = TreeRepairEngine(tree=tree)
        new_source = EvidenceSource(url="https://example.com/update")
        new_summary = BoundedSummary(summary="v2.0 released recently", key_entities=[], key_metrics={})

        repair_result = engine.apply_repair(
            target_node_id="node_a",
            new_claim="New Version",
            new_summary=new_summary,
            new_source=new_source,
            conflict_type=ConflictType.TEMPORAL_UPDATE,
            reason="Version increment",
        )

        assert repair_result.target_node_id == "node_a"
        assert len(repair_result.pruned_node_ids) == 0
        assert tree.nodes["node_a"].bounded_summary.summary == "v2.0 released recently"
        assert tree.nodes["node_b"].status == EvidenceNodeStatus.ACTIVE

    def test_contradiction_cascade_pruning(self) -> None:
        tree = EvidenceTree()
        node_a = _make_node("node_a", "Premise A", "Earth is flat", deps=["root"])
        node_b = _make_node("node_b", "Inference B", "Edge is dangerous", deps=["node_a"])
        node_c = _make_node("node_c", "Inference C", "Don't sail near edge", deps=["node_b"])
        node_independent = _make_node("node_indep", "Solar fact", "Sun is hot", deps=["root"])

        tree.add_node(node_a)
        tree.add_node(node_b)
        tree.add_node(node_c)
        tree.add_node(node_independent)

        engine = TreeRepairEngine(tree=tree)
        new_source = EvidenceSource(url="https://nasa.gov/earth")
        new_summary = BoundedSummary(summary="Earth is spherical", key_entities=["Earth"], key_metrics={})

        repair_result = engine.apply_repair(
            target_node_id="node_a",
            new_claim="Correct Premise A",
            new_summary=new_summary,
            new_source=new_source,
            conflict_type=ConflictType.CONTRADICTION,
            reason="Scientific consensus confirms spherical shape",
        )

        assert "node_b" in repair_result.pruned_node_ids
        assert "node_c" in repair_result.pruned_node_ids
        assert tree.nodes["node_b"].status == EvidenceNodeStatus.PRUNED_INVALIDATED
        assert tree.nodes["node_c"].status == EvidenceNodeStatus.PRUNED_INVALIDATED
        assert tree.nodes["node_indep"].status == EvidenceNodeStatus.ACTIVE
        active_slice = tree.format_bounded_slice()
        assert "Earth is spherical" in active_slice
        assert "Edge is dangerous" not in active_slice
        assert "Don't sail near edge" not in active_slice
        assert "Sun is hot" in active_slice

    def test_oscillation_guard_freezes_as_disputed(self) -> None:
        tree = EvidenceTree()
        node = _make_node("controversial_node", "Perspective 1", "Approach A is faster", deps=["root"])
        tree.add_node(node)

        engine = TreeRepairEngine(tree=tree)
        src = EvidenceSource(url="https://bench.com")

        engine.apply_repair(
            "controversial_node",
            "Perspective 2",
            BoundedSummary(summary="Approach B is faster", key_entities=[], key_metrics={}),
            src,
            ConflictType.CONTRADICTION,
            "Benchmark 1",
        )
        assert tree.nodes["controversial_node"].revision_depth == 1
        assert tree.nodes["controversial_node"].status == EvidenceNodeStatus.ACTIVE

        engine.apply_repair(
            "controversial_node",
            "Perspective 1 again",
            BoundedSummary(summary="Approach A is faster", key_entities=[], key_metrics={}),
            src,
            ConflictType.CONTRADICTION,
            "Benchmark 2",
        )
        assert tree.nodes["controversial_node"].revision_depth == 2

        res = engine.apply_repair(
            "controversial_node",
            "Perspective 2 again",
            BoundedSummary(summary="Approach B is faster", key_entities=[], key_metrics={}),
            src,
            ConflictType.CONTRADICTION,
            "Benchmark 3",
        )
        assert res.is_disputed is True
        node_after = tree.get_node("controversial_node")
        assert node_after is not None and node_after.status == EvidenceNodeStatus.DISPUTED
        slice_text = tree.format_bounded_slice()
        assert "[DISPUTED]" in slice_text
