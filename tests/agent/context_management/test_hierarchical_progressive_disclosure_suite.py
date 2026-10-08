# [INPUT]: AdaptiveBranchFoldingSentry, AssembledSupplyContext, DisclosureExpansionResult, HierarchicalContextTreeBuilder, HierarchicalProgressiveDisclosureContextSupplySuite, HierarchyLevel, HierarchyNode, HierarchyTree, ProgressiveDisclosureConfig
# [OUTPUT]: test_hierarchical_progressive_disclosure_suite.py
# [POS]: tests/agent/context_management/test_hierarchical_progressive_disclosure_suite.py

"""Comprehensive unit tests for HierarchicalProgressiveDisclosureContextSupplySuite.

Verifies:
1. Declarative tree construction with bidirectional child links and level-based defaults.
2. Progressive disclosure runtime drill-down via expand_business_context meta-tool.
3. Adaptive branch folding sentry enforcing active L3 limits and completed node collapse.
4. Multi-tier prompt assembly across L1 Backbone, L2 Cohort, and L3 Detail leaves.
5. Error handling for missing node IDs and schema definition exports.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.hierarchical_supply import (
    AdaptiveBranchFoldingSentry,
    AssembledSupplyContext,
    DisclosureExpansionResult,
    HierarchicalContextTreeBuilder,
    HierarchicalProgressiveDisclosureContextSupplySuite,
    HierarchyLevel,
    HierarchyNode,
    HierarchyTree,
    ProgressiveDisclosureConfig,
)


def _build_sample_enterprise_tree() -> HierarchyTree:
    builder = HierarchicalContextTreeBuilder()

    # L1 Backbone
    builder.add_node(
        node_id="l1_campaign_q4",
        title="2026 Q4 Double-11 Coupon Campaign",
        level=HierarchyLevel.L1_BACKBONE,
        summary="Q4 promotional campaign targeting high-value enterprise churn risks.",
        full_content="Executive directive: Allocate $500k coupon budget to retain enterprise clients with renewal dates within 60 days.",
    )

    # L2 Cohorts
    builder.add_node(
        node_id="l2_cohort_at_risk",
        title="High-Churn-Risk Customer Cohort (N=142)",
        level=HierarchyLevel.L2_COHORT,
        summary="142 accounts with drop in monthly API call volume > 30%.",
        full_content="Detailed cohort criteria: Contract value >= $50k/yr, telemetry drop >= 30% over past 4 weeks.",
        parent_id="l1_campaign_q4",
    )
    builder.add_node(
        node_id="l2_cohort_upsell",
        title="Rapid-Growth Expansion Cohort (N=85)",
        level=HierarchyLevel.L2_COHORT,
        summary="85 accounts operating at 90% seat capacity.",
        full_content="Criteria: Reached 90%+ license quota with positive CSAT surveys.",
        parent_id="l1_campaign_q4",
    )

    # L3 Details
    builder.add_node(
        node_id="l3_invoice_acme_corp",
        title="Acme Corp Transaction Ledger & Ticket Log",
        level=HierarchyLevel.L3_DETAIL,
        summary="Account ACME-9021 invoice dispute on rate card.",
        full_content="Invoice #88912 ($62,000) disputed due to legacy discount disagreement. Last contact on Oct 2.",
        parent_id="l2_cohort_at_risk",
    )
    builder.add_node(
        node_id="l3_telemetry_globex",
        title="Globex International Traffic Dip Metrics",
        level=HierarchyLevel.L3_DETAIL,
        summary="Traffic metrics drop from 1.2M req/day to 400k req/day.",
        full_content="Telemetry breakdown: Service outage on Sept 28 caused routing switch to fallback provider.",
        parent_id="l2_cohort_at_risk",
    )
    builder.add_node(
        node_id="l3_upsell_soylent",
        title="Soylent Industries Tier Upgrade Request",
        level=HierarchyLevel.L3_DETAIL,
        summary="Requested 200 additional Enterprise seats.",
        full_content="Contract addendum drafted for $120k ARR increase. Pending legal approval.",
        parent_id="l2_cohort_upsell",
    )

    return builder.build()


def test_tree_builder_structure_and_links() -> None:
    tree = _build_sample_enterprise_tree()

    assert len(tree.root_node_ids) == 1
    assert tree.root_node_ids[0] == "l1_campaign_q4"
    assert len(tree.nodes) == 6

    # Verify L1 has L2 children
    l1_node = tree.nodes["l1_campaign_q4"]
    assert "l2_cohort_at_risk" in l1_node.children_ids
    assert "l2_cohort_upsell" in l1_node.children_ids
    assert l1_node.is_expanded is True  # L1 defaults to expanded

    # Verify L2 defaults to collapsed
    l2_node = tree.nodes["l2_cohort_at_risk"]
    assert l2_node.is_expanded is False
    assert "l3_invoice_acme_corp" in l2_node.children_ids

    # Verify invalid parent error
    invalid_builder = HierarchicalContextTreeBuilder()
    invalid_builder.add_node(
        node_id="orphan",
        title="Orphan",
        level=HierarchyLevel.L2_COHORT,
        summary="orphan",
        full_content="orphan",
        parent_id="non_existent_parent",
    )
    with pytest.raises(ValueError, match="not found in builder"):
        invalid_builder.build()


def test_progressive_disclosure_expansion_and_tool_schema() -> None:
    tree = _build_sample_enterprise_tree()
    suite = HierarchicalProgressiveDisclosureContextSupplySuite(tree=tree)

    # Tool definition schema
    schema = suite.get_tool_definition()
    assert schema["name"] == "expand_business_context"
    assert "node_id" in schema["parameters"]["properties"]

    # Initial context assembly (L1 expanded, L2/L3 folded)
    ctx1 = suite.assemble_context()
    assert ctx1.active_l1_count == 1
    assert ctx1.active_l2_count == 0
    assert ctx1.active_l3_count == 0
    assert "### Tier 1: Backbone Objectives" in ctx1.assembled_prompt
    assert "(FOLDED)" in ctx1.assembled_prompt
    assert "expand_business_context('l2_cohort_at_risk')" in ctx1.assembled_prompt

    # Expand L2 node
    res2 = suite.expand_business_context("l2_cohort_at_risk")
    assert res2.node_id == "l2_cohort_at_risk"
    assert "Contract value >= $50k/yr" in res2.expanded_text
    assert res2.tokens_added > 0

    ctx2 = suite.assemble_context()
    assert ctx2.active_l2_count == 1
    assert "**[l2_cohort_at_risk] High-Churn-Risk Customer Cohort (N=142) (EXPANDED)**" in ctx2.assembled_prompt


def test_adaptive_branch_folding_sentry() -> None:
    tree = _build_sample_enterprise_tree()
    # Configure tight ceiling of 2 active L3 nodes
    config = ProgressiveDisclosureConfig(max_active_l3_nodes=2, auto_fold_completed_branches=True)
    suite = HierarchicalProgressiveDisclosureContextSupplySuite(config=config, tree=tree)

    # 1. Expand first L3
    res1 = suite.expand_business_context("l3_invoice_acme_corp")
    assert len(res1.folded_nodes) == 0

    # 2. Expand second L3
    res2 = suite.expand_business_context("l3_telemetry_globex")
    assert len(res2.folded_nodes) == 0

    ctx_two = suite.assemble_context()
    assert ctx_two.active_l3_count == 2

    # 3. Expand third L3 -> Exceeds max_active_l3_nodes=2 -> Oldest should be folded
    res3 = suite.expand_business_context("l3_upsell_soylent")
    assert len(res3.folded_nodes) == 1
    assert res3.folded_nodes[0] == "l3_invoice_acme_corp"

    ctx_three = suite.assemble_context()
    assert ctx_three.active_l3_count == 2
    # Verify folded node is now collapsed
    assert suite.current_tree.nodes["l3_invoice_acme_corp"].is_expanded is False
    assert suite.current_tree.nodes["l3_upsell_soylent"].is_expanded is True


def test_mark_branch_completed_and_folding() -> None:
    tree = _build_sample_enterprise_tree()
    suite = HierarchicalProgressiveDisclosureContextSupplySuite(tree=tree)

    # Expand node
    suite.expand_business_context("l3_invoice_acme_corp")
    assert suite.current_tree.nodes["l3_invoice_acme_corp"].is_expanded is True

    # Mark completed with conclusion
    suite.mark_branch_completed(
        "l3_invoice_acme_corp",
        conclusion="Discount approved at 15% rate, retention risk mitigated.",
    )

    node = suite.current_tree.nodes["l3_invoice_acme_corp"]
    assert node.is_completed is True
    assert node.is_expanded is False
    assert "[Completed Conclusion]" in node.summary

    # Context assembly renders COMPLETED status
    ctx = suite.assemble_context()
    assert "**[l3_invoice_acme_corp] Acme Corp Transaction Ledger & Ticket Log (COMPLETED)**" in ctx.assembled_prompt


def test_empty_tree_and_missing_node() -> None:
    suite = HierarchicalProgressiveDisclosureContextSupplySuite()
    ctx = suite.assemble_context()
    assert ctx.total_tokens == 0
    assert ctx.assembled_prompt == ""

    with pytest.raises(KeyError, match="does not exist"):
        suite.expand_business_context("unknown_node")
