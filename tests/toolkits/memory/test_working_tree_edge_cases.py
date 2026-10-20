"""Edge cases and defensive unit tests for ReTree working memory and pruning engine.

Covers:
- Cyclic dependency defense (ensuring visited set terminates traversal)
- Multi-parent DAG cascade pruning behavior
- Node upsert and idempotent wiring
- Empty tree and root-only slice formatting
- Malformed LLM arbitration responses and safe fallback
- Extreme length and regex special character handling without ReDoS
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
            key_entities=["H100", "B200"],
            key_metrics={"gain": "2.5x"},
            estimated_tokens=len(summary) // 4,
        ),
        source=EvidenceSource(
            url=url or f"https://example.com/{node_id}",
            title=f"Source for {node_id}",
            snippet=f"Snippet for {node_id}",
            content_hash=content_hash,
        ),
        dependencies=deps or [],
        dependents=[],
        created_at=now,
        updated_at=now,
    )


class TestWorkingTreeEdgeCases:
    """Edge cases for EvidenceTree graph integrity and defensive execution."""

    def test_cyclic_dependency_prevention(self) -> None:
        """Verify cyclic dependency between nodes does not cause infinite loop during traversal."""
        tree = EvidenceTree()
        node_a = _make_node("node_a", "Claim A", "Summary A", deps=["root"])
        node_b = _make_node("node_b", "Claim B", "Summary B", deps=["node_a"])
        tree.add_node(node_a)
        tree.add_node(node_b)

        # Intentionally inject cyclic dependency directly
        tree.nodes["node_a"].dependents.append("node_b")
        tree.nodes["node_b"].dependents.append("node_a")
        tree.nodes["node_a"].dependencies.append("node_b")
        tree.nodes["node_b"].dependencies.append("node_a")

        # Downstream traversal must terminate safely without recursion error
        downstream = tree.get_downstream_dependents("node_a")
        assert set(downstream) == {"node_a", "node_b"} or "node_b" in downstream

        # Upstream traversal must terminate safely
        upstream = tree.get_upstream_dependencies("node_a")
        assert "node_b" in upstream

    def test_multi_parent_dag_cascade_pruning(self) -> None:
        """Verify multi-parent DAG: Node C depends on both A and B.

        When A is refuted, downstream C is cascade pruned even if B was valid.
        """
        tree = EvidenceTree()
        node_a = _make_node("node_a", "Premise A (Flawed)", "Premise A summary", deps=["root"])
        node_b = _make_node("node_b", "Premise B (Valid)", "Premise B summary", deps=["root"])
        node_c = _make_node("node_c", "Joint Inference C", "Inference relying on A & B", deps=["node_a", "node_b"])
        node_d = _make_node("node_d", "Downstream D", "Relies on C", deps=["node_c"])

        tree.add_node(node_a)
        tree.add_node(node_b)
        tree.add_node(node_c)
        tree.add_node(node_d)

        engine = TreeRepairEngine(tree=tree)
        new_source = EvidenceSource(url="https://example.com/corrected-a")
        new_summary = BoundedSummary(summary="Corrected A summary")

        repair_result = engine.apply_repair(
            target_node_id="node_a",
            new_claim="Premise A (Corrected)",
            new_summary=new_summary,
            new_source=new_source,
            conflict_type=ConflictType.CONTRADICTION,
            reason="Refuted by empirical proof",
        )

        # C and D must be cascade pruned
        assert "node_c" in repair_result.pruned_node_ids
        assert "node_d" in repair_result.pruned_node_ids
        assert tree.nodes["node_c"].status == EvidenceNodeStatus.PRUNED_INVALIDATED
        assert tree.nodes["node_d"].status == EvidenceNodeStatus.PRUNED_INVALIDATED
        # Node B remains active
        assert tree.nodes["node_b"].status == EvidenceNodeStatus.ACTIVE

    def test_node_upsert_idempotence_and_wiring(self) -> None:
        """Verify re-adding an existing node ID merges dependencies cleanly without duplication."""
        tree = EvidenceTree()
        node1 = _make_node("dup_id", "Initial claim", "Initial summary", deps=["root"])
        tree.add_node(node1)

        node2 = _make_node("dep_node", "Dep claim", "Dep summary", deps=["root"])
        tree.add_node(node2)

        # Add node with same ID but additional dependency
        updated_node = _make_node("dup_id", "Updated claim", "Updated summary", deps=["dep_node"])
        tree.add_node(updated_node)

        stored = tree.get_node("dup_id")
        assert stored is not None
        assert stored.claim == "Updated claim"
        # Dependencies must be merged
        assert "root" in stored.dependencies
        assert "dep_node" in stored.dependencies
        # Ensure dep_node lists dup_id as dependent
        dep_node = tree.get_node("dep_node")
        assert dep_node is not None
        assert "dup_id" in dep_node.dependents

    def test_empty_tree_and_root_only_formatting(self) -> None:
        """Verify tree with only root node formats safely with no active sub-nodes."""
        tree = EvidenceTree(root_id="root_only", root_claim="Analyze something")
        slice_text = tree.format_bounded_slice(max_tokens=2000)
        assert "EVIDENCE WORKING MEMORY" in slice_text
        # Root node itself is not printed as an active evidence item
        assert "[root_only]" not in slice_text

    @pytest.mark.asyncio
    async def test_detector_malformed_llm_response_handling(self) -> None:
        """Verify detector handles non-conforming or unparseable LLM output safely."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        # Non-conforming output without standard VERDICT prefix
        mock_response.content = "I think maybe these two claims are somewhat different but I cannot decide."
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        detector = FastContradictionDetector(arbitrator_llm=mock_llm)
        existing = [_make_node("n1", "Quantum computing speedup", "Speedup is exponential")]

        verdict = await detector.acheck_conflict(
            new_claim="Quantum computing speedup",
            new_summary="Speedup is quadratic in search",
            existing_nodes=existing,
        )
        # Should gracefully fall back to NONE rather than throwing exception
        assert verdict.conflict_type == ConflictType.NONE
        assert "Arbitration fallback to neutral" in verdict.reason

    def test_detector_extreme_length_and_special_chars(self) -> None:
        """Verify detector runs safely on extreme length texts and regex reserved characters."""
        detector = FastContradictionDetector()
        special_claim = r"Regex characters [test] (.*+?^) ${abc} | \w+ \d+ :;!? &*#@ `code`"
        large_summary = "A" * 15000 + " refuted and false " + "B" * 15000

        existing = [_make_node("n1", special_claim, "Valid summary")]

        verdict = detector.check_conflict(
            new_claim=special_claim,
            new_summary=large_summary,
            existing_nodes=existing,
        )
        assert verdict.conflict_type in (ConflictType.CONTRADICTION, ConflictType.NONE, ConflictType.COMPLEMENTARY)
        assert verdict.conflicting_node_id == "n1"
