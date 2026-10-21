"""Unit tests for Diamond Topology DAG and Blinded Adversarial Auditor."""

import pytest
from myrm_agent_harness.agent.sub_agents.diamond_graph import (
    AuditorPerspective,
    BlindedAdversarialAuditor,
    DiamondGraphOrchestrator,
    DiamondNode,
    DiamondStage,
    RealityAnchorSpec,
    RealityAnchorType,
)


def test_diamond_pipeline_construction() -> None:
    orch = DiamondGraphOrchestrator()
    fan_out_specs = [
        {"title": "Search Benchmark Papers", "query": "agent graph"},
        {"title": "Inspect Micro-benchmarks", "query": "concurrency"},
        {"title": "Profile Memory Leak", "query": "memory"},
    ]
    fans, reduce_node, synth_node = orch.create_diamond_pipeline(
        goal="Design diamond architecture", fan_out_specs=fan_out_specs
    )

    assert len(fans) == 3
    assert reduce_node.stage == DiamondStage.REDUCE
    assert len(reduce_node.depends_on) == 3
    assert synth_node.stage == DiamondStage.SYNTHESIZE
    assert synth_node.depends_on == [reduce_node.node_id]


def test_false_dependency_pruner() -> None:
    orch = DiamondGraphOrchestrator()
    fan_specs = [{"title": "Task 1"}, {"title": "Task 2"}, {"title": "Task 3"}]
    fans, _, _ = orch.create_diamond_pipeline(goal="Test Pruning", fan_out_specs=fan_specs)

    # Artificially inject cross fan-out dependency (Task 2 depends on Task 1)
    fans[1].depends_on.append(fans[0].node_id)
    assert fans[0].node_id in fans[1].depends_on

    pruned = orch.prune_false_dependencies()
    assert len(pruned) == 1
    assert pruned[0] == (fans[0].node_id, fans[1].node_id)
    assert fans[1].is_pruned is True
    assert fans[0].node_id not in fans[1].depends_on


def test_census_sentinel_and_dead_node_retry() -> None:
    orch = DiamondGraphOrchestrator()
    fan_specs = [{"title": "Branch A"}, {"title": "Branch B"}]
    fans, _, _ = orch.create_diamond_pipeline(goal="Census Test", fan_out_specs=fan_specs)

    # Dispatch wave
    initial_census = orch.dispatch_fan_out()
    assert initial_census.dispatched_count == 2
    assert initial_census.received_count == 0
    assert initial_census.is_healthy is False
    assert len(initial_census.missing_nodes) == 2

    # Complete Branch A only
    orch.record_node_completion(fans[0].node_id, output_artifact="Branch A Findings")
    census_partial = orch.check_census()
    assert census_partial.received_count == 1
    assert census_partial.is_healthy is False
    assert census_partial.missing_nodes == [fans[1].node_id]

    # Retry dead nodes
    retried = orch.retry_dead_nodes()
    assert retried == [fans[1].node_id]

    # Complete Branch B
    orch.record_node_completion(fans[1].node_id, output_artifact="Branch B Findings")
    census_healthy = orch.check_census()
    assert census_healthy.is_healthy is True
    assert len(census_healthy.missing_nodes) == 0


def test_deterministic_reduce_and_synthesis() -> None:
    orch = DiamondGraphOrchestrator()
    fan_specs = [{"title": "Data 1"}, {"title": "Data 2"}]
    fans, _, _ = orch.create_diamond_pipeline(goal="Reduce Test", fan_out_specs=fan_specs)

    # Trying reduce before all branches complete raises error
    with pytest.raises(RuntimeError, match="Census failure"):
        orch.execute_deterministic_reduce()

    # Complete branches with overlapping lines to test deduplication
    orch.record_node_completion(
        fans[0].node_id, output_artifact="Metric A: 100\nMetric B: 200\nSummary statement"
    )
    orch.record_node_completion(
        fans[1].node_id, output_artifact="Metric B: 200\nMetric C: 300\nSummary statement"
    )

    reduced = orch.execute_deterministic_reduce()
    assert "Metric A: 100" in reduced
    assert "Metric B: 200" in reduced
    assert "Metric C: 300" in reduced

    synth = orch.execute_synthesis()
    assert synth.startswith("Consolidated Architecture Synthesis:")
    assert "Metric A: 100" in synth
    assert "[End of Synthesis]" in synth


def test_blinded_adversarial_auditor_isolation() -> None:
    auditor = BlindedAdversarialAuditor()
    node = DiamondNode(
        node_id="gen-01",
        title="Implementation Plan",
        stage=DiamondStage.SYNTHESIZE,
        output_artifact="[Architecture Reference] Verified production layout with zero-loss durability.",
        cot_reasoning_internal="I am thinking about using a simpler trick, but it might have flaws...",
    )

    # Verify CoT is stripped
    stripped = auditor.strip_cot_for_audit(node)
    assert "zero-loss durability" in stripped
    assert "I am thinking" not in stripped

    # Test audit perspectives
    rev_fact = auditor.audit_perspective(stripped, AuditorPerspective.FACT_ACCURACY)
    assert rev_fact.passed is True
    assert rev_fact.isolated_context_verified is True

    rev_time = auditor.audit_perspective(stripped, AuditorPerspective.TIMELINESS)
    assert rev_time.passed is True

    rev_cite = auditor.audit_perspective(stripped, AuditorPerspective.CITATION_AUTHORITY)
    assert rev_cite.passed is True

    verdict = auditor.evaluate_delivery(stripped)
    assert verdict.passed is True
    assert verdict.pass_count == 3
    assert "Blinded consensus approved" in verdict.consensus_summary


def test_reality_anchor_verification_and_frozen_rule() -> None:
    auditor = BlindedAdversarialAuditor()
    artifact = "[Report] System deployment completed with green health checks."

    # Anchor 1: Exit code 0 (passes)
    anchor_pass = RealityAnchorSpec(
        anchor_type=RealityAnchorType.EXIT_CODE_ZERO,
        target_id="test_runner",
        expected_value="0",
        actual_value="0",
    )
    # Anchor 2: Hash mismatch (fails)
    anchor_fail = RealityAnchorSpec(
        anchor_type=RealityAnchorType.HASH_MATCH,
        target_id="bundle_sha256",
        expected_value="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        actual_value="corrupted_hash_value",
    )

    # When all anchors pass
    verdict_success = auditor.evaluate_delivery(artifact, reality_anchors=[anchor_pass])
    assert verdict_success.passed is True

    # Frozen rule: if any anchor fails, verdict MUST fail despite 3/3 LLM pass!
    verdict_fail = auditor.evaluate_delivery(artifact, reality_anchors=[anchor_pass, anchor_fail])
    assert verdict_fail.passed is False
    assert "One or more objective reality anchors violated" in verdict_fail.consensus_summary
